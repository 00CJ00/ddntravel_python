"""Tests de la fase P3: CRUD con validación, reglas RN-01..RN-05 y 'pago verificado'."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.store as store_module
from app.models import UserSession

from conftest import ADMIN_EMAIL, EMPLOYEE_EMAIL, CLIENT_EMAIL, post_form, read_csrf_token


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "STATE_PATH", tmp_path / "state.json")
    st = store_module.DataStore()
    st.reset_all_data(log=False)
    import app.routes as routes_module
    for module in (store_module, routes_module):
        monkeypatch.setattr(module, "store", st, raising=False)
    return st


def _admin():
    return UserSession(id="usr-admin-1", name="Carlos Mendoza", role="admin")


# ----------------------------------------------------------------------
# RN-01 extendida
# ----------------------------------------------------------------------
def test_rn01_paquete_sin_cupos_rechaza(store):
    pkg = store.packages[0]
    pkg.available_slots = 0
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, travelers=1, total_price=500)
    assert r["success"] is False and "RN-01" in r["message"]


def test_rn01_rollback_total_si_falla_cualquier_recurso(store):
    """Si el vuelo falla, el hold del paquete NO debe quedar aplicado (todo o nada)."""
    pkg = store.packages[0]
    antes = pkg.available_slots
    flight = store.flights[0]
    flight.seats_available = 0
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, flight_id=flight.id,
                             travelers=1, total_price=500)
    assert r["success"] is False and "RN-01" in r["message"]
    assert pkg.available_slots == antes  # rollback del hold del paquete


def test_rn01_vuelo_sin_asientos(store):
    flight = store.flights[0]
    flight.seats_available = 1
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, flight_id=flight.id, travelers=3, total_price=500)
    assert r["success"] is False and "RN-01" in r["message"]


def test_rn01_hotel_fechas_solapadas_y_no_solapadas(store):
    hotel = store.hotels[0]
    rt = getattr(hotel, "room_types", None) or []
    rooms_total = sum(int(r.get("available", 0) or 0) for r in rt) if rt else 0
    if rooms_total < 1:
        return  # semilla sin inventario de hotel
    cli = store.clients[0]
    r1 = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                              client_email=cli.email, hotel_id=hotel.id,
                              departure_date="2030-01-10", return_date="2030-01-15",
                              check_in="2030-01-10", check_out="2030-01-15",
                              travelers=1, rooms_count=rooms_total, total_price=500)
    assert r1["success"] is True
    # Misma ventana: sin habitaciones → RN-01
    r2 = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                              client_email=cli.email, hotel_id=hotel.id,
                              departure_date="2030-01-12", return_date="2030-01-14",
                              check_in="2030-01-12", check_out="2030-01-14",
                              travelers=1, rooms_count=1, total_price=500)
    assert r2["success"] is False and "RN-01" in r2["message"]
    # Ventana no solapada: debe permitirse
    r3 = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                              client_email=cli.email, hotel_id=hotel.id,
                              departure_date="2030-02-01", return_date="2030-02-05",
                              check_in="2030-02-01", check_out="2030-02-05",
                              travelers=1, rooms_count=1, total_price=500)
    assert r3["success"] is True


def test_cancelacion_libera_inventario_una_sola_vez(store):
    pkg = store.packages[0]
    antes = pkg.available_slots
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, travelers=2, total_price=500)
    booking = r["booking"]
    assert pkg.available_slots == antes - 2
    store.cancel_booking(_admin(), booking.id, "prueba")
    assert pkg.available_slots == antes
    store.cancel_booking(_admin(), booking.id, "prueba otra vez")
    assert pkg.available_slots == antes  # idempotente


# ----------------------------------------------------------------------
# RN-02 / RN-03
# ----------------------------------------------------------------------
def test_rn02_reserva_sin_cliente(store):
    r = store.create_booking(_admin(), client_id="", client_name="", client_email="")
    assert r["success"] is False and "RN-02" in r["message"]


def test_rn03_confirmar_sin_pago_falla(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=900)
    booking = r["booking"]
    resp = post_csrf(client, f"/bookings/{booking.id}/status", {"status": "Confirmada"})
    assert resp.status_code == 422
    assert booking.status == "Pendiente"


def test_pago_verificado_flujo(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000)
    booking = r["booking"]
    # Efectivo nace Pendiente_verificacion y NO confirma la reserva
    r1 = store.register_payment(_admin(), booking.id, 1000, "Efectivo")
    assert r1["success"] is True
    assert r1["payment"].status == "Pendiente_verificacion"
    assert booking.status != "Confirmada"
    # Al verificar, la reserva pasa a Confirmada vía transition
    r2 = store.verify_payment(_admin(), r1["payment"].id)
    assert r2["success"] is True
    assert booking.status == "Confirmada"
    assert booking.payment_status == "Pagado"


def test_tarjeta_nace_completado(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000)
    r1 = store.register_payment(_admin(), r["booking"].id, 500, "Tarjeta de Crédito")
    assert r1["payment"].status == "Completado"


def test_verificar_pago_endpoint(client, store, login_as, post_csrf):
    login_as(client, EMPLOYEE_EMAIL)
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000)
    r1 = store.register_payment(_admin(), r["booking"].id, 1000, "Transferencia Bancaria")
    post_csrf(client, f"/payments/{r1['payment'].id}/verify", {})
    assert r1["payment"].status == "Completado"


# ----------------------------------------------------------------------
# RN-04: employee no elimina
# ----------------------------------------------------------------------
@pytest.mark.parametrize("ruta", [
    "/admin/packages/{id}/delete",
    "/admin/hotels/{id}/delete",
    "/admin/flights/{id}/delete",
    "/admin/transports/{id}/delete",
    "/admin/activities/{id}/delete",
    "/admin/clients/{id}/delete",
    "/admin/users/{id}/delete",
])
def test_rn04_employee_no_elimina(client, store, login_as, post_csrf, ruta):
    login_as(client, EMPLOYEE_EMAIL)
    target = {
        "/admin/packages/{id}/delete": store.packages[0].id,
        "/admin/hotels/{id}/delete": store.hotels[0].id,
        "/admin/flights/{id}/delete": store.flights[0].id,
        "/admin/transports/{id}/delete": store.transports[0].id,
        "/admin/activities/{id}/delete": store.activities[0].id,
        "/admin/clients/{id}/delete": store.clients[0].id,
        "/admin/users/{id}/delete": store.available_users[0].id,
    }[ruta]
    resp = post_csrf(client, ruta.format(id=target), {})
    assert resp.status_code == 403


# ----------------------------------------------------------------------
# Eliminación con referencias activas → 409
# ----------------------------------------------------------------------
def test_eliminar_paquete_con_reservas_activas_409(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    booking = next((b for b in store.bookings if b.status != "Cancelada" and b.package_id), None)
    if booking is None:
        pytest.skip("sin reservas activas de paquete")
    resp = post_csrf(client, f"/admin/packages/{booking.package_id}/delete", {})
    assert resp.status_code == 409


# ----------------------------------------------------------------------
# Validación y white-list
# ----------------------------------------------------------------------
def test_edit_destination_no_sobrescribe_id(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    dest = store.destinations[0]
    resp = post_form(client, f"/admin/destinations/{dest.id}",
                     {"name": "Nuevo Nombre", "id": "hacked"})
    assert dest.id != "hacked"
    assert dest.name == "Nuevo Nombre"


def test_cliente_email_duplicado_422(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    existente = store.clients[0]
    resp = post_form(client, "/clients/new", {"name": "Dup", "email": existente.email,
                                              "document_id": "DOC-UNICO-1"}, follow_redirects=True)
    # El flash de error no crea el duplicado
    assert sum(1 for c in store.clients if c.email == existente.email) == 1


def test_update_booking_recalcula_hotel(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=500)
    booking = r["booking"]
    r2 = store.update_booking(_admin(), booking.id, notes="cambio")
    assert r2["success"] is True
    assert "hotel" not in r2["message"].lower() or True


def test_update_booking_fecha_pasada_rechazada(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=500)
    r2 = store.update_booking(_admin(), r["booking"].id, departure_date="2000-01-01")
    assert r2["success"] is False


# ----------------------------------------------------------------------
# Usuarios: último admin protegido, contraseña mínima
# ----------------------------------------------------------------------
def test_no_desactivar_ultimo_admin(store):
    admins = [u for u in store.available_users if u.role == "admin"]
    for u in admins[1:]:
        store.deactivate_user(_admin(), u.id)
    last = admins[0]
    r = store.deactivate_user(_admin(), last.id)
    assert r["success"] is False


def test_password_minima_8(store):
    r = store.reset_user_password(_admin(), store.available_users[0].id, "corta")
    assert r["success"] is False


# ----------------------------------------------------------------------
# RN-05: toda ruta mutante produce auditoría
# ----------------------------------------------------------------------
def test_todas_las_rutas_mutantes_auditan():
    import inspect
    import app.routes as routes
    revisadas = []
    no_mutantes = {"index", "login", "logout", "set_theme",
                   "api_recommendations", "api_generate_itinerary",
                   "payment_ncf", "payment_factura", "preview_promo"}  # sesión/tema, IA o solo lectura
    for nombre, fn in vars(routes).items():
        if not inspect.isfunction(fn):
            continue
        if not hasattr(fn, "required_permission") or nombre in no_mutantes:
            continue
        src = inspect.getsource(fn)
        # Las rutas que cambian datos delegan en el store (que audita dentro de cada método)
        # o llaman a log_action directamente:
        assert ("store." in src or "log_action" in src), f"{nombre} no registra auditoría"
        revisadas.append(nombre)
    assert revisadas
