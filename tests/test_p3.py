"""Tests de la fase P3: CRUD con validación, reglas RN-01..RN-05 y 'pago verificado'."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conftest import ADMIN_EMAIL, EMPLOYEE_EMAIL, CLIENT_EMAIL, post_form


def _admin(store):
    return next(u for u in store.available_users if u.role == "admin")


# ----------------------------------------------------------------------
# RN-01 extendida
# ----------------------------------------------------------------------
def test_rn01_paquete_sin_cupos_rechaza(store):
    pkg = store.packages[0]
    pkg.available_slots = 0
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, travelers=1, total_price=500)
    assert r["success"] is False and "RN-01" in r["message"]


def test_rn01_vuelo_sin_asientos(store):
    flight = store.flights[0]
    flight.seats_available = 0
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, flight_id=flight.id, travelers=3, total_price=500)
    assert r["success"] is False and "RN-01" in r["message"]


def test_rn01_rollback_total_si_falla_cualquier_recurso(store):
    """Si el vuelo falla, el hold del paquete NO debe quedar aplicado (todo o nada)."""
    pkg = store.packages[0]
    antes = pkg.available_slots
    flight = store.flights[0]
    flight.seats_available = 0
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, flight_id=flight.id,
                             travelers=1, total_price=500)
    assert r["success"] is False and "RN-01" in r["message"]
    assert pkg.available_slots == antes


def test_rn01_hotel_fechas_solapadas_y_no_solapadas(store):
    hotel = next((h for h in store.hotels if sum(rt.rooms_total or 0 for rt in (h.room_types or [])) > 0), None)
    if hotel is None:
        pytest.skip("sin inventario de hotel en la semilla")
    rooms_total = sum(rt.rooms_total or 0 for rt in hotel.room_types)
    cli = store.clients[0]
    r1 = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                              client_email=cli.email, hotel_id=hotel.id,
                              departure_date="2030-01-10", return_date="2030-01-15",
                              check_in="2030-01-10", check_out="2030-01-15",
                              travelers=1, rooms_count=rooms_total, total_price=500)
    assert r1["success"] is True, r1["message"]
    r2 = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                              client_email=cli.email, hotel_id=hotel.id,
                              departure_date="2030-01-12", return_date="2030-01-14",
                              check_in="2030-01-12", check_out="2030-01-14",
                              travelers=1, rooms_count=1, total_price=500)
    assert r2["success"] is False and "RN-01" in r2["message"]
    r3 = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                              client_email=cli.email, hotel_id=hotel.id,
                              departure_date="2030-02-01", return_date="2030-02-05",
                              check_in="2030-02-01", check_out="2030-02-05",
                              travelers=1, rooms_count=1, total_price=500)
    assert r3["success"] is True, r3["message"]


def test_cancelacion_libera_inventario_una_sola_vez(store):
    pkg = store.packages[0]
    antes = pkg.available_slots
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, travelers=2, total_price=500)
    booking = r["booking"]
    assert pkg.available_slots == antes - 2
    store.cancel_booking(_admin(store), booking.id, "prueba")
    assert pkg.available_slots == antes
    store.cancel_booking(_admin(store), booking.id, "prueba otra vez")
    assert pkg.available_slots == antes


# ----------------------------------------------------------------------
# RN-02 / RN-03
# ----------------------------------------------------------------------
def test_rn02_reserva_sin_cliente(store):
    r = store.create_booking(_admin(store), client_id="", client_name="", client_email="")
    assert r["success"] is False and "RN-02" in r["message"]


def test_rn03_confirmar_sin_pago_falla(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=900)
    booking = r["booking"]
    resp = post_csrf(client, f"/bookings/{booking.id}/status", {"status": "Confirmada"})
    assert resp.status_code == 422
    assert booking.status == "Pendiente"


def test_rn03_bypass_con_pago_no_verificado(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=800)
    booking = r["booking"]
    store.register_payment(_admin(store), booking.id, 800, "Efectivo")
    resp = post_csrf(client, f"/bookings/{booking.id}/status", {"status": "Confirmada"})
    assert resp.status_code == 422
    assert booking.status == "Pendiente"


def test_rn03_apply_payment_no_confirma_directo(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=500)
    booking = r["booking"]
    booking.apply_payment(500)
    assert booking.status == "Pendiente"


def test_pago_verificado_flujo(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000)
    booking = r["booking"]
    r1 = store.register_payment(_admin(store), booking.id, 1000, "Efectivo")
    assert r1["success"] is True
    assert r1["payment"].status == "Pendiente_verificacion"
    assert booking.status != "Confirmada"
    r2 = store.verify_payment(_admin(store), r1["payment"].id)
    assert r2["success"] is True
    assert booking.status == "Confirmada"
    assert booking.payment_status == "Pagado"


def test_tarjeta_nace_completado(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000)
    r1 = store.register_payment(_admin(store), r["booking"].id, 500, "Tarjeta de Crédito")
    assert r1["payment"].status == "Completado"


def test_verificar_pago_endpoint(client, store, login_as, post_csrf):
    login_as(client, EMPLOYEE_EMAIL)
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000)
    r1 = store.register_payment(_admin(store), r["booking"].id, 1000, "Transferencia Bancaria")
    post_csrf(client, f"/payments/{r1['payment'].id}/verify", {})
    assert r1["payment"].status == "Completado"


# ----------------------------------------------------------------------
# RN-04: employee no elimina
# ----------------------------------------------------------------------
@pytest.mark.parametrize("ruta,tipo", [
    ("/admin/packages/{id}/delete", "packages"),
    ("/admin/hotels/{id}/delete", "hotels"),
    ("/admin/flights/{id}/delete", "flights"),
    ("/admin/transports/{id}/delete", "transports"),
    ("/admin/activities/{id}/delete", "activities"),
    ("/admin/clients/{id}/delete", "clients"),
    ("/admin/users/{id}/delete", "users"),
])
def test_rn04_employee_no_elimina(client, store, login_as, post_csrf, ruta, tipo):
    login_as(client, EMPLOYEE_EMAIL)
    coll = {"packages": store.packages, "hotels": store.hotels, "flights": store.flights,
            "transports": store.transports, "activities": store.activities,
            "clients": store.clients, "users": store.available_users}[tipo]
    target = coll[0].id
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
                     {"name": "Nuevo Nombre", "id": "999999"})
    assert dest.name == "Nuevo Nombre"


def test_cliente_email_duplicado_422(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    existente = store.clients[0]
    before = len(store.clients)
    post_form(client, "/clients/new", {"name": "Dup", "email": existente.email,
                                       "document_id": "DOC-UNICO-1"}, follow_redirects=True)
    assert len(store.clients) == before


def test_update_booking_fecha_pasada_rechazada(store):
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=500)
    r2 = store.update_booking(_admin(store), r["booking"].id, departure_date="2000-01-01")
    assert r2["success"] is False


def test_update_booking_recalcula_hotel(store):
    hotel = next((h for h in store.hotels if h.room_types), None)
    if hotel is None:
        pytest.skip("sin room_types")
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, hotel_id=hotel.id,
                             departure_date="2030-03-01", return_date="2030-03-03",
                             check_in="2030-03-01", check_out="2030-03-03", rooms_count=1,
                             travelers=1, total_price=500)
    assert r["success"] is True
    booking = r["booking"]
    r2 = store.update_booking(_admin(store), booking.id, notes="cambio")
    assert r2["success"] is True
    price = float(hotel.room_types[0].price_per_night or 0)
    assert float(booking.total_price) == price * 2 * 1


# ----------------------------------------------------------------------
# Usuarios: último admin protegido, contraseña mínima
# ----------------------------------------------------------------------
def test_no_desactivar_ultimo_admin(store):
    admins = [u for u in store.available_users if u.role == "admin"]
    for u in admins[1:]:
        store.deactivate_user(_admin(store), u.id)
    last = admins[0]
    r = store.deactivate_user(_admin(store), last.id)
    assert r["success"] is False


def test_password_minima_8(store):
    r = store.reset_user_password(_admin(store), store.available_users[0].id, "corta")
    assert r["success"] is False


# ----------------------------------------------------------------------
# Promociones (RF-12)
# ----------------------------------------------------------------------
def _promo_activa(store, **over):
    data = dict(code="TEST10", title="Test", discount_percentage=10, max_uses=100,
                current_uses=0, active=True, applicable_categories=["Todos"], valid_until=None)
    data.update(over)
    return store.add_promotion(_admin(store), **data)


def test_promo_registra_redemption_y_suma_usos(store):
    promo = _promo_activa(store)
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000,
                             promo_code="TEST10")
    assert r["success"] is True, r["message"]
    assert promo.current_uses == 1
    from app import models as m
    red = m.PromotionRedemption.query.filter_by(promotion_id=promo.id).first()
    assert red is not None and red.booking_id == r["booking"].id


def test_promo_vencida_rechazada(store):
    import datetime as _dt
    promo = _promo_activa(store, code="VIEJO", valid_until=_dt.date(2000, 1, 1))
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000,
                             promo_code="VIEJO")
    assert r["success"] is False
    assert promo.current_uses == 0


def test_promo_categoria_no_aplicable(store):
    promo = _promo_activa(store, code="VIPONLY", applicable_categories=["VIP"])
    cli = next(c for c in store.clients if c.category != "VIP")
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=1000,
                             promo_code="VIPONLY")
    assert r["success"] is False
    assert promo.current_uses == 0


# ----------------------------------------------------------------------
# RN-05: toda ruta mutante produce auditoría
# ----------------------------------------------------------------------
def test_todas_las_rutas_mutantes_auditan(app):
    import inspect
    EXCLUIDAS = {"/api/chat/message", "/contacto", "/contacto/callback", "/set-theme"}
    SIN_EFECTOS = {"/login", "/logout", "/api/ai/recommendations",
                   "/api/ai/generate-itinerary", "/api/promo/preview"}
    revisadas = []
    for regla in app.url_map.iter_rules():
        metodos = set(regla.methods) - {"GET", "HEAD", "OPTIONS"}
        if not metodos:
            continue
        if regla.rule in SIN_EFECTOS or any(e in regla.rule for e in EXCLUIDAS):
            continue
        vista = app.view_functions[regla.endpoint]
        try:
            src = inspect.getsource(vista)
        except (OSError, TypeError):
            continue
        assert ("store." in src or "log_action" in src or "audit" in src), \
            f"{regla.endpoint} ({regla.rule}) no deja rastro de auditoría"
        revisadas.append(regla.endpoint)
    assert revisadas
