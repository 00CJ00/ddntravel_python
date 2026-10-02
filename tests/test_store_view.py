"""Pruebas de fugas de datos: nada de otros clientes en el HTML ni en el JS.

Comprueba el store filtrado (``app/view.py``) de los tres roles, en las páginas
que antes exponían el store crudo: los modales globales de ``base.html`` (que
iteraban todos los clientes y todas las reservas) y ``window.DDN_DATA``.
"""
from __future__ import annotations

import pytest

from conftest import ADMIN_EMAIL, CLIENT_EMAIL, EMPLOYEE_EMAIL, login_as


RUTAS_POR_ROL = {
    "admin": ["/dashboard", "/clients", "/bookings", "/payments", "/documents", "/audit"],
    "employee": ["/dashboard", "/clients", "/bookings", "/payments", "/documents", "/promotions"],
    "client": ["/client-portal", "/documents", "/edit-profile", "/packages", "/destinations"],
}


def _html(client, ruta) -> str:
    response = client.get(ruta)
    assert response.status_code in (200, 302), f"{ruta} devolvio {response.status_code}"
    return response.get_data(as_text=True)


@pytest.mark.parametrize("rol,correo", [
    ("admin", ADMIN_EMAIL),
    ("employee", EMPLOYEE_EMAIL),
    ("client", CLIENT_EMAIL),
])
def test_ninguna_pagina_devuelve_500(rol, correo, client, store, login_as):
    login_as(client, correo)
    for ruta in RUTAS_POR_ROL[rol]:
        assert client.get(ruta).status_code in (200, 302), f"{rol} -> {ruta}"


@pytest.mark.parametrize("ruta", RUTAS_POR_ROL["client"])
def test_html_de_cliente_no_contiene_datos_de_otros(ruta, client, store, login_as):
    login_as(client, CLIENT_EMAIL)
    html = _html(client, ruta)
    for otro in store.clients:
        if otro.email == CLIENT_EMAIL or not otro.email:
            continue
        assert otro.email not in html, f"{ruta} filtra el email de {otro.name}"
    for reserva in store.bookings:
        if reserva.client_email == CLIENT_EMAIL:
            continue
        assert reserva.booking_code not in html, f"{ruta} filtra la reserva ajena {reserva.booking_code}"


def test_ddn_data_de_cliente_no_incluye_otros_clientes(client, store, login_as):
    login_as(client, CLIENT_EMAIL)
    html = _html(client, "/client-portal")
    assert "DDN_DATA" in html
    for otro in store.clients:
        if otro.email != CLIENT_EMAIL and otro.email:
            assert otro.email not in html


def test_modales_de_cliente_no_ofrecen_reservas_ajenas(client, store, login_as):
    """El selector de pagos de base.html iteraba todas las reservas del store."""
    login_as(client, CLIENT_EMAIL)
    html = _html(client, "/client-portal")
    ajenas = [b for b in store.bookings if b.client_email != CLIENT_EMAIL]
    assert ajenas, "la semilla debe tener reservas de otros clientes"
    assert "DDN-2026-" in html, "el cliente deberia ver al menos su propia reserva"
    for reserva in ajenas:
        assert reserva.booking_code not in html


def test_cliente_no_ve_hoteles_ni_vuelos_internos(client, store, login_as):
    login_as(client, CLIENT_EMAIL)
    html = _html(client, "/client-portal")
    for hotel in store.hotels:
        assert hotel.name not in html


def test_admin_sigue_viendo_todos_los_clientes(client, store, login_as):
    """El filtrado no debe recortar la vista del personal interno."""
    login_as(client, ADMIN_EMAIL)
    html = _html(client, "/clients")
    for otro in store.clients:
        if otro.email:
            assert otro.email in html


def test_store_view_filtra_por_propiedad(store):
    """Prueba unitaria de la vista, sin pasar por HTTP."""
    from app.view import store_view
    from app.models.legacy import UserSession

    usuario = UserSession(id="usr-x", name="Cliente X", email=CLIENT_EMAIL, role="client", avatar="")
    vista = store_view(store, usuario)
    assert vista.clients, "el cliente debe ver su propia ficha"
    assert all(c.email == CLIENT_EMAIL for c in vista.clients)
    assert all(b.client_email == CLIENT_EMAIL for b in vista.bookings)
    assert vista.hotels == [] and vista.flights == [] and vista.audit_logs == []
    assert vista.available_users == []
    assert vista.packages, "el catálogo público sí debe estar disponible"
