"""Comprobaciones de plantilla: CSRF en todos los formularios POST.

Regla de la fase P1: todo ``<form method="post">`` renderizado debe incluir el
token CSRF, y los botones/enlaces de acciones que el usuario no puede ejecutar
no deben aparecer.
"""
from __future__ import annotations

import re

import pytest
from conftest import ADMIN_EMAIL, CLIENT_EMAIL, EMPLOYEE_EMAIL
from markupsafe import escape

# Formularios que se envían con fetch/JS y por eso no llevan method="post".
FORMULARIOS_JS = {"chat-form", "itinerary-form", "recommend-form"}

POST_FORM_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
METHOD_RE = re.compile(r"method\s*=\s*[\"']?post", re.IGNORECASE)
ID_RE = re.compile(r"id\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
CSRF_RE = re.compile(r"name=[\"']csrf_token[\"']", re.IGNORECASE)
SVG_RE = re.compile(r"<svg\b[^>]*>(.*?)</svg>", re.IGNORECASE | re.DOTALL)

RUTAS = {
    "admin": ["/dashboard", "/clients", "/bookings", "/payments", "/documents", "/promotions", "/audit"],
    "employee": ["/dashboard", "/clients", "/bookings", "/payments", "/documents", "/promotions"],
    "client": ["/client-portal", "/documents", "/edit-profile", "/packages", "/destinations", "/contacto"],
}


def _forms_sin_csrf(html: str) -> list[str]:
    """Devuelve los id de los formularios POST que no incluyen el token."""
    sin_token = []
    for match in POST_FORM_RE.finditer(html):
        etiqueta = match.group(0)
        if not METHOD_RE.search(etiqueta):
            continue
        id_form = ID_RE.search(etiqueta)
        nombre = id_form.group(1) if id_form else "?"
        # El cuerpo del formulario va hasta el cierre correspondiente.
        fin = html.find("</form>", match.end())
        cuerpo = html[match.end():fin if fin != -1 else len(html)]
        if nombre in FORMULARIOS_JS:
            continue
        if not CSRF_RE.search(cuerpo):
            sin_token.append(nombre)
    return sin_token


@pytest.mark.parametrize("rol,correo", [
    ("admin", ADMIN_EMAIL),
    ("employee", EMPLOYEE_EMAIL),
    ("client", CLIENT_EMAIL),
])
def test_todos_los_formularios_post_llevan_csrf(rol, correo, client, store, login_as):
    login_as(client, correo)
    for ruta in RUTAS[rol]:
        response = client.get(ruta)
        assert response.status_code in (200, 302), f"{rol} -> {ruta} ({response.status_code})"
        sin_token = _forms_sin_csrf(response.get_data(as_text=True))
        assert not sin_token, f"{ruta} tiene formularios POST sin token CSRF: {sin_token}"


@pytest.mark.parametrize("ruta", RUTAS["client"])
def test_cliente_no_ve_botones_de_acciones_internas(ruta, client, store, login_as):
    """El cliente no debe ver eliminar documentos ni crear/activar promociones.

    Nota: Jinja renderiza URLs, no nombres de endpoint, así que se buscan los
    fragmentos de ruta que genera ``url_for``.
    """
    login_as(client, CLIENT_EMAIL)
    html = client.get(ruta).get_data(as_text=True)
    assert "/promotions/new" not in html, f"{ruta} ofrece crear promociones a un cliente"
    assert "/delete" not in html, f"{ruta} ofrece eliminar documentos a un cliente"
    assert "/clients/new" not in html, f"{ruta} ofrece registrar clientes a un cliente"


def test_empleado_no_ve_eliminar_documentos(client, store, login_as):
    """RN-04: eliminar informacion critica es solo de administradores."""
    login_as(client, EMPLOYEE_EMAIL)
    html = client.get("/documents").get_data(as_text=True)
    assert "/delete" not in html
    assert "/documents/new" in html, "el empleado si puede registrar documentos"


def test_admin_ve_eliminar_documentos(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    html = client.get("/documents").get_data(as_text=True)
    assert "/delete" in html


def test_empleado_no_ve_activar_promociones(client, store, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    html = client.get("/promotions").get_data(as_text=True)
    assert "/toggle" not in html
    assert "/promotions/new" not in html


@pytest.mark.parametrize("rol,correo,rutas", [
    ("employee", EMPLOYEE_EMAIL, ["/packages", "/flights", "/transports", "/activities"]),
    ("client", CLIENT_EMAIL, ["/packages", "/activities"]),
])
def test_solo_admin_ve_controles_de_gestion_del_catalogo(
    rol, correo, rutas, client, store, login_as
):
    login_as(client, correo)
    for ruta in rutas:
        response = client.get(ruta)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "data-catalog-new" not in html
        assert "data-catalog-edit" not in html
        assert "data-catalog-delete" not in html


def test_admin_ve_controles_de_gestion_del_catalogo(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    for ruta, recurso in [
        ("/packages", "package"),
        ("/flights", "flight"),
        ("/transports", "transport"),
        ("/activities", "activity"),
    ]:
        response = client.get(ruta)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert f'data-catalog-new="{recurso}"' in html
        assert f'data-catalog-edit="{recurso}"' in html
        assert "data-catalog-delete" in html


def test_contacto_muestra_iconos_validos_y_ubicacion_de_infotep_santiago(
    client, store, login_as
):
    login_as(client, ADMIN_EMAIL)
    response = client.get("/contacto")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    icon_contents = SVG_RE.findall(html)
    assert icon_contents
    assert all(re.search(r"<(?:path|polygon|rect|circle|polyline|line)\b", icon) for icon in icon_contents)
    assert "INFOTEP Santiago" in html
    assert "Santiago de los Caballeros" in html
    assert "Rep%C3%BAblica+Dominicana" in html
    assert 'rel="noopener noreferrer"' in html


def test_staff_booking_modal_lists_allied_hotels_with_clear_field_help(
    client, store, login_as
):
    login_as(client, ADMIN_EMAIL)
    response = client.get("/bookings")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    hotels_with_rooms = [hotel for hotel in store.hotels if hotel.room_types]
    assert hotels_with_rooms
    assert f"{len(hotels_with_rooms)} hoteles aliados disponibles." in html
    assert 'id="booking-hotel"' in html
    assert 'aria-describedby="booking-hotel-help"' in html
    assert 'id="booking-services-heading"' in html
    for hotel in hotels_with_rooms:
        assert str(escape(hotel.name)) in html
    assert "Nombre, documento de identidad y edad de cada pasajero." in html


def test_client_booking_modal_does_not_offer_internal_hotel_or_flight_options(
    client, store, login_as
):
    login_as(client, CLIENT_EMAIL)
    response = client.get("/client-portal")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'name="hotel_id"' not in html
    assert 'name="flight_id"' not in html
    assert "Los hoteles aliados y vuelos se cotizan con un asesor" in html
    assert store.hotels[0].name not in html
