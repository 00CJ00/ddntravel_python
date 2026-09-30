"""Comprobaciones de plantilla: CSRF en todos los formularios POST.

Regla de la fase P1: todo ``<form method="post">`` renderizado debe incluir el
token CSRF, y los botones/enlaces de acciones que el usuario no puede ejecutar
no deben aparecer.
"""
from __future__ import annotations

import re

import pytest

from conftest import ADMIN_EMAIL, CLIENT_EMAIL, EMPLOYEE_EMAIL, login_as

# Formularios que se envían con fetch/JS y por eso no llevan method="post".
FORMULARIOS_JS = {"chat-form", "itinerary-form", "recommend-form"}

POST_FORM_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
METHOD_RE = re.compile(r"method\s*=\s*[\"']?post", re.IGNORECASE)
ID_RE = re.compile(r"id\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
CSRF_RE = re.compile(r"name=[\"']csrf_token[\"']", re.IGNORECASE)

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
