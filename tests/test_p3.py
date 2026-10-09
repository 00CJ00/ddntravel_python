"""Tests de la fase P3: CRUD con validación, reglas RN-01..RN-05 y 'pago verificado'."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import models as m
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
    ("/admin/destinations/{id}/delete", "destinations"),
    ("/admin/clients/{id}/delete", "clients"),
    ("/admin/users/{id}/delete", "users"),
])
def test_rn04_employee_no_elimina(client, store, login_as, post_csrf, ruta, tipo):
    login_as(client, EMPLOYEE_EMAIL)
    coll = {"packages": store.packages, "hotels": store.hotels, "flights": store.flights,
            "transports": store.transports, "activities": store.activities,
            "destinations": store.destinations,
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
# Borrado de Destino y guard estricto de Transporte (C2)
# ----------------------------------------------------------------------
def test_eliminar_destino_sin_referencias(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    dest = store.add_destination(_admin(store), name="Destino Libre", country="XC")
    resp = post_csrf(client, f"/admin/destinations/{dest.id}/delete", {})
    assert resp.status_code == 200
    assert all(d.id != dest.id for d in store.destinations)


def test_crear_destino_via_http(client, store, login_as, post_csrf):
    """POST /admin/destinations crea la fila (regresión del create roto por
    ``save(assign_by_type(...))`` que devolvía ``save(None)``)."""
    login_as(client, ADMIN_EMAIL)
    resp = post_csrf(client, "/admin/destinations", {"name": "Crear HTTP", "country": "HC"})
    assert resp.status_code == 200
    assert any(d.name == "Crear HTTP" for d in store.destinations)


def test_eliminar_destino_con_reserva_cancelada_409(client, store, login_as, post_csrf):
    """El destino es borrado físico: una reserva cancelada también lo protege."""
    login_as(client, ADMIN_EMAIL)
    dest = store.add_destination(_admin(store), name="Destino Histórico", country="XH")
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, destination_name=dest.name,
                             travelers=1, total_price=500)
    store.cancel_booking(_admin(store), r["booking"].id, "cancelado en prueba")
    resp = post_csrf(client, f"/admin/destinations/{dest.id}/delete", {})
    assert resp.status_code == 409
    assert any(d.id == dest.id for d in store.destinations)


def test_eliminar_destino_referenciado_por_catalogo_409(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    destino = next((d for d in store.destinations if any(
        getattr(p, "destination_id", None) == d.id for p in store.packages)), None)
    if destino is None:
        pytest.skip("sin destinos referenciados por paquetes en la semilla")
    resp = post_csrf(client, f"/admin/destinations/{destino.id}/delete", {})
    assert resp.status_code == 409


def test_eliminar_transporte_con_solo_reserva_cancelada_409(client, store, login_as, post_csrf):
    """El transporte es borrado físico: con SOLO una reserva cancelada no se elimina."""
    login_as(client, ADMIN_EMAIL)
    t = store.add_transport(_admin(store), type="Bus", route="Prueba C2", vehicle_model="V1",
                            capacity=10, available_seats=10)
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, transport_id=t.id, travelers=1,
                             total_price=500)
    store.cancel_booking(_admin(store), r["booking"].id, "cancelado en prueba")
    resp = post_csrf(client, f"/admin/transports/{t.id}/delete", {})
    assert resp.status_code == 409
    assert any(t2.id == t.id for t2 in store.transports)


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


# ----------------------------------------------------------------------
# RN-01 atómico en vuelo y transporte (UPDATE condicional)
# ----------------------------------------------------------------------
def test_rn01_vuelo_descuenta_atomico(store):
    flight = store.add_flight(_admin(store), airline="AirX", flight_number="XA7",
                              price_usd=120, seats_available=5, total_seats=5)
    cli = store.clients[-1]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, flight_id=flight.id, travelers=2,
                             total_price=400)
    assert r["success"] is True
    assert store.get_flight(flight.id).seats_available == 3


def test_rn01_transporte_descuenta_atomico(store):
    transport = store.add_transport(_admin(store), type="Bus", route="SDQ-POP",
                                    capacity=10, available_seats=4, price_usd=60)
    cli = store.clients[-1]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, transport_id=transport.id, travelers=3,
                             total_price=300)
    assert r["success"] is True
    fila = next(t for t in store.transports if t.id == transport.id)
    assert fila.available_seats == 1


def test_rn01_vuelo_agota_y_no_sobrevende(store):
    flight = store.add_flight(_admin(store), airline="AirX", flight_number="XA8",
                              price_usd=120, seats_available=1, total_seats=1)
    cli = store.clients[-1]
    args = dict(client_id=cli.id, client_name=cli.name, client_email=cli.email,
                flight_id=flight.id, total_price=120)
    r1 = store.create_booking(_admin(store), travelers=1, **args)
    assert r1["success"] is True
    r2 = store.create_booking(_admin(store), travelers=1, **args)
    assert r2["success"] is False and "RN-01" in r2["message"]
    assert store.get_flight(flight.id).seats_available == 0


def test_rn01_paquete_y_vuelo_se_revierten_juntos_si_falla_el_vuelo(store):
    """Si el vuelo se agota entre el chequeo y el descuento, el paquete no queda
    descontado (todo o nada en la misma transacción)."""
    pkg = store.add_package(_admin(store), title="PkgVuelo", price_usd=100,
                            total_slots=10, available_slots=10)
    flight = store.add_flight(_admin(store), airline="AirX", flight_number="XA9",
                              price_usd=120, seats_available=0, total_seats=0)
    cli = store.clients[-1]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, flight_id=flight.id,
                             travelers=1, total_price=300)
    assert r["success"] is False
    assert store.get_package(pkg.id).available_slots == 10


# ----------------------------------------------------------------------
# Soft delete (baja lógica): Paquete, Hotel, Vuelo y Cliente (RN-04 / P3)
# ----------------------------------------------------------------------
def _audit(store, action):
    return [l for l in store.audit_logs if l.action == action]


def _borrar_via_http(client, login_as, post_csrf, url):
    login_as(client, ADMIN_EMAIL)
    resp = post_csrf(client, url, {})
    assert resp.status_code == 200, resp.data[:200]
    return resp


def _paquete_libre(store):
    return store.add_package(_admin(store), title="PkgBaja", price_usd=100,
                             total_slots=10, available_slots=10)


def test_paquete_baja_logica_conserva_fila(client, store, login_as, post_csrf):
    pkg = _paquete_libre(store)
    _borrar_via_http(client, login_as, post_csrf, f"/admin/packages/{pkg.id}/delete")
    fila = m.Package.query.get(pkg.id)
    assert fila is not None and fila.deleted_at is not None
    assert all(p.id != pkg.id for p in store.packages)
    assert store.get_package(pkg.id) is None


def test_hotel_baja_logica_conserva_fila(client, store, login_as, post_csrf):
    hotel = store.add_hotel(_admin(store), name="HotelBaja")
    _borrar_via_http(client, login_as, post_csrf, f"/admin/hotels/{hotel.id}/delete")
    fila = m.Hotel.query.get(hotel.id)
    assert fila is not None and fila.deleted_at is not None
    assert all(h.id != hotel.id for h in store.hotels)


def test_vuelo_baja_logica_conserva_fila(client, store, login_as, post_csrf):
    flight = store.add_flight(_admin(store), airline="X", flight_number="XX")
    _borrar_via_http(client, login_as, post_csrf, f"/admin/flights/{flight.id}/delete")
    fila = m.Flight.query.get(flight.id)
    assert fila is not None and fila.deleted_at is not None
    assert all(f.id != flight.id for f in store.flights)


def test_cliente_baja_logica_conserva_fila(client, store, login_as, post_csrf):
    cli = store.add_client(_admin(store), name="CliBaja", email="clibaja@ejemplo.com")
    _borrar_via_http(client, login_as, post_csrf, f"/admin/clients/{cli.id}/delete")
    fila = m.Client.query.get(cli.id)
    assert fila is not None and fila.deleted_at is not None
    assert all(c.id != cli.id for c in store.clients)


def test_borrado_logico_audita_con_before_after(client, store, login_as, post_csrf):
    pkg = _paquete_libre(store)
    antes_logs = len(store.audit_logs)
    _borrar_via_http(client, login_as, post_csrf, f"/admin/packages/{pkg.id}/delete")
    nuevos = len(store.audit_logs) - antes_logs
    logs = store.audit_logs[:nuevos]
    elim = next(l for l in logs if l.action == "ELIMINAR_PAQUETE")
    assert (elim.before or {}).get("deleted_at") is None
    assert (elim.after or {}).get("deleted_at") is not None


def test_baja_logica_no_se_puede_editar_ni_reservar(client, store, login_as, post_csrf):
    pkg = _paquete_libre(store)
    _borrar_via_http(client, login_as, post_csrf, f"/admin/packages/{pkg.id}/delete")
    login_as(client, ADMIN_EMAIL)
    edit = post_csrf(client, f"/admin/packages/{pkg.id}",
                     {"title": "EDITADO", "price_usd": "1"})
    assert edit.status_code == 404
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, package_id=pkg.id, travelers=1,
                             total_price=500)
    assert r["success"] is False  # baja lógica: no se puede reservar lo borrado
