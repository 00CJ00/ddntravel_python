"""Pruebas de propiedad de datos (IDOR) y de fugas entre clientes.

Objetivo de la fase P1: un cliente solo puede ver y modificar lo suyo, y ninguna
respuesta a un cliente contiene datos personales de otros clientes
(invariante declarada en AGENTS.md).

Las comprobaciones sobre el HTML renderizado (modales, portal, perfil) viven en
``test_store_view.py``, junto con el store filtrado que las hace posibles.
"""
from __future__ import annotations

import pytest

from conftest import CLIENT_EMAIL


# ----------------------------------------------------------------------
# Escalada de privilegios (un cliente contra rutas de personal interno)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("ruta", [
    "/audit",
    "/clients",
    "/promotions",
    "/bookings",
    "/payments",
])
def test_cliente_recibe_403_en_rutas_de_personal(client, store, login_as, ruta):
    login_as(client, CLIENT_EMAIL)
    assert client.get(ruta).status_code == 403, ruta


def test_cliente_no_puede_restablecer_datos(client, store, login_as, post_csrf, make_app):
    """/reset es POST y exige el permiso data:reset (solo admin)."""
    login_as(client, CLIENT_EMAIL)
    total_antes = len(store.bookings)
    assert post_csrf(client, "/reset", {"confirm": "RESTABLECER"}).status_code == 403
    assert len(store.bookings) == total_antes, "el reset se ejecuto sin permisos"


def test_reset_exige_confirmacion_explicita(client, store, login_as, post_csrf, make_app):
    """Admin sin el token de confirmación no borra nada."""
    login_as(client, "admin@ddntravel.com")
    total_antes = len(store.bookings)
    assert post_csrf(client, "/reset", {}).status_code in (302, 404)
    assert len(store.bookings) == total_antes, "el reset se ejecuto sin confirmacion"


def test_cliente_no_puede_anexar_reserva_ajena(client, store, login_as, post_csrf):
    """Aunque manipule client_id, la reserva se crea a su propio nombre (RN-02)."""
    login_as(client, CLIENT_EMAIL)
    otro = next(c for c in store.clients if c.email != CLIENT_EMAIL)
    ids_antes = {b.id for b in store.bookings}
    post_csrf(client, "/bookings/new", {
        "client_id": otro.id,
        "package_id": store.packages[0].id,
        "travelers": "2",
        "departure_date": "2030-01-10",
        "return_date": "2030-01-20",
    })
    # Ojo: el store inserta al principio de la lista, así que se compara por id.
    nuevas = [b for b in store.bookings if b.id not in ids_antes]
    assert nuevas, "la reserva no llego a crearse (revisar disponibilidad del paquete)"
    assert all(b.client_email == CLIENT_EMAIL for b in nuevas), "se creo la reserva de otro cliente"


def test_cliente_no_cancela_reserva_ajena(client, store, login_as, post_csrf):
    login_as(client, CLIENT_EMAIL)
    ajena = next(b for b in store.bookings if b.client_email != CLIENT_EMAIL)
    estado_inicial = ajena.status
    post_csrf(client, f"/bookings/{ajena.id}/cancel", {"reason": "intento ilegítimo"})
    assert ajena.status == estado_inicial


def test_cliente_cancela_su_reserva_pendiente(client, store, login_as, post_csrf):
    """Un cliente cancela su propia reserva Pendiente (no depende del seed).

    El test crea la reserva con la ruta real, así que el estado de partida
    ("Pendiente") está garantizado aunque la semilla cambie.
    """
    login_as(client, CLIENT_EMAIL)
    propia = _crear_reserva_pendiente_del_cliente(client, store, post_csrf)
    assert propia.status == "Pendiente", f"la reserva deberia iniciar en Pendiente, no {propia.status}"

    respuesta = post_csrf(client, f"/bookings/{propia.id}/cancel", {"reason": "cambio de planes"})
    assert respuesta.status_code in (200, 302)
    assert propia.status == "Cancelada", f"la reserva quedo en {propia.status}"


def test_cliente_no_cancela_una_reserva_ya_confirmada(client, store, login_as, post_csrf):
    """Solo se puede cancelar lo que está Pendiente (matriz de permisos)."""
    login_as(client, CLIENT_EMAIL)
    propia = _crear_reserva_pendiente_del_cliente(client, store, post_csrf)
    # El personal confirma la reserva y ya no debe poder cancelarla el cliente.
    admin = next(u for u in store.available_users if u.role == "admin")
    store.register_payment(admin, propia.id, propia.total_price, "Tarjeta de Crédito")
    assert store.update_booking_status(admin, propia.id, "Confirmada")["success"]
    assert propia.status == "Confirmada"

    post_csrf(client, f"/bookings/{propia.id}/cancel", {"reason": "should not work"})
    assert propia.status == "Confirmada", "el cliente cancelo una reserva confirmada"


def _crear_reserva_pendiente_del_cliente(client, store, post_csrf):
    """Crea una reserva propia del cliente demo usando la ruta /bookings/new.

    Devuelve el objeto ``Booking`` recién creado. Se apoya en la respuesta de la
    ruta (que renderiza bookings.html con error si falla) para no ser silencioso
    si la creación no ocurre.
    """
    ids_antes = {b.id for b in store.bookings}
    respuesta = post_csrf(client, "/bookings/new", {
        "client_id": "cualquiera",  # el cliente se toma de la sesión (IDOR)
        "package_id": store.packages[0].id,
        "travelers": "1",
        "departure_date": "2030-03-15",
        "return_date": "2030-03-25",
    })
    nuevas = [b for b in store.bookings if b.id not in ids_antes]
    assert nuevas, (f"no se creó la reserva (HTTP {respuesta.status_code}); "
                    f"la creación debe ser explícita para que el test sea determinista")
    return nuevas[0]


def test_cliente_no_confirma_reserva(client, store, login_as, post_csrf):
    """RN-03: el cambio de estado es exclusivo del personal interno."""
    login_as(client, CLIENT_EMAIL)
    propia = next(b for b in store.bookings if b.client_email == CLIENT_EMAIL)
    estado_inicial = propia.status
    post_csrf(client, f"/bookings/{propia.id}/status", {"status": "Confirmada"})
    assert propia.status == estado_inicial


def test_cliente_no_anexa_documento_a_otro_expediente(client, store, login_as, post_csrf):
    login_as(client, CLIENT_EMAIL)
    otro = next(c for c in store.clients if c.email != CLIENT_EMAIL)
    ids_antes = {d.id for d in store.documents}
    post_csrf(client, "/documents/new", {
        "client_id": otro.id,
        "doc_type": "Pasaporte",
        "document_number": "9999",
    })
    nuevos = [d for d in store.documents if d.id not in ids_antes]
    assert all(d.client_id != otro.id for d in nuevos), "documento subido al expediente ajeno"


def test_cliente_no_elimina_documentos(client, store, login_as, post_csrf):
    """RN-04: solo administradores eliminan informacion critica."""
    login_as(client, CLIENT_EMAIL)
    total_antes = len(store.documents)
    doc = store.documents[0]
    post_csrf(client, f"/documents/{doc.id}/delete", {})
    assert len(store.documents) == total_antes


# ----------------------------------------------------------------------
# Facturacion: permiso + propiedad antes del 501 de la fase P4
# ----------------------------------------------------------------------
def test_factura_ajena_devuelve_404_no_501(client, store, login_as):
    """No se filtra ni la existencia de pagos ajenos: 404 antes del 501."""
    ajena = _crear_pago_de_otro_cliente(store)
    login_as(client, CLIENT_EMAIL)
    assert client.get(f"/payments/{ajena.id}/factura").status_code == 404
    assert client.get(f"/payments/{ajena.id}/ncf").status_code == 404


def _crear_reserva_con_saldo(store, email: str, total: float = 1000.0):
    """Reserva propia sin pagos: garantiza saldo pendiente para probar pagos/facturas."""
    from app.models import UserSession
    cliente = next(c for c in store.clients if c.email == email)
    admin = next(u for u in store.available_users if u.role == "admin")
    resultado = store.create_booking(
        admin, client_id=cliente.id, client_name=cliente.name, client_email=cliente.email,
        travelers=1, total_price=total,
    )
    assert resultado["success"] is True, resultado
    return resultado["booking"]


def test_ncf_propio_devuelve_501_pendiente_p4(client, store, login_as):
    login_as(client, CLIENT_EMAIL)
    propia = _crear_reserva_con_saldo(store, CLIENT_EMAIL)
    pago = _registrar_pago(store, propia)
    response = client.get(f"/payments/{pago.id}/ncf")
    assert response.status_code == 501
    assert "P4" in response.get_data(as_text=True)


def _registrar_pago(store, reserva, monto=25.0):
    """Registra un pago real sobre la reserva, sin depender de la semilla."""
    admin = next(u for u in store.available_users if u.role == "admin")
    resultado = store.register_payment(admin, reserva.id, monto, "Tarjeta de Crédito")
    assert resultado.get("success"), resultado
    return next(p for p in store.payments if p.booking_id == reserva.id)


def _crear_pago_de_otro_cliente(store):
    """Pago sobre una reserva de otro cliente (setup explícito del test)."""
    ajena_email = next(b.client_email for b in store.bookings
                       if b.client_email and b.client_email != CLIENT_EMAIL)
    ajena = _crear_reserva_con_saldo(store, ajena_email)
    return _registrar_pago(store, ajena)


def test_factura_de_pago_inexistente_devuelve_404(client, login_as):
    login_as(client, CLIENT_EMAIL)
    assert client.get("/payments/pag-inexistente/factura").status_code == 404


def test_empleado_no_registra_pagos_de_reserva_inexistente(client, store, login_as, post_csrf):
    login_as(client, "sofia.v@ddntravel.com")
    post_csrf(client, "/payments/new", {
        "booking_id": "bkg-inexistente",
        "amount": "100",
        "payment_method": "Efectivo",
    })
    assert all(p.booking_id != "bkg-inexistente" for p in store.payments)


# ----------------------------------------------------------------------
# Perfil: cada quien edita su propia ficha
# ----------------------------------------------------------------------
def test_cliente_no_puede_editar_perfil_de_otro(client, store, login_as, post_csrf):
    login_as(client, CLIENT_EMAIL)
    otro = next(c for c in store.clients if c.email != CLIENT_EMAIL)
    nombre_original = otro.name
    post_csrf(client, "/edit-profile", {
        "client_id": otro.id,
        "name": "Hackeado",
        "phone": otro.phone,
    })
    assert otro.name == nombre_original


def test_cliente_actualiza_su_propio_perfil(client, store, login_as, post_csrf):
    login_as(client, CLIENT_EMAIL)
    propio = next(c for c in store.clients if c.email == CLIENT_EMAIL)
    post_csrf(client, "/edit-profile", {
        "client_id": "otro-id-cualquiera",
        "name": "Roberto Gomez Editado",
        "phone": propio.phone,
    })
    assert propio.name == "Roberto Gomez Editado"


def test_perfil_sin_cliente_asociado_no_revienta(client, store, login_as):
    """Un usuario cliente sin ficha no debe producir un 500."""
    usuario = next(u for u in store.available_users if u.role == "client")
    usuario.email = "huerfano@example.com"
    login_as(client, "huerfano@example.com")
    assert client.get("/edit-profile").status_code == 302
    assert client.get("/client-portal").status_code in (200, 302)
