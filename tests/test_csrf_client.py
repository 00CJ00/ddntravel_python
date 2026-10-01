"""Pruebas del paso 7: CSRF en el cliente (JavaScript) y permisos expuestos.

El navegador debe poder enviar el token por ``fetch`` (cabecera X-CSRFToken) y
por formulario dinámico. Aquí se comprueba que base.html publica el token, que el
JS lo usa y que un POST sin token es rechazado.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import CLIENT_EMAIL, EMPLOYEE_EMAIL, login_as

JS_RELATIVE = Path("static") / "js" / "app.js"


def _js() -> str:
    return (Path(__file__).resolve().parents[1] / JS_RELATIVE).read_text(encoding="utf-8")


def test_base_publica_el_token_csrf(client, store, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    html = client.get("/dashboard").get_data(as_text=True)
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match, "falta <meta name=csrf-token> en base.html"
    assert len(match.group(1)) > 20


def test_javascript_usa_el_token_en_las_cabeceras():
    js = _js()
    assert "X-CSRFToken" in js, "las peticiones fetch no envian el token"
    assert "getCsrfToken" in js
    assert 'meta[name="csrf-token"]' in js
    # Ningún fetch directo a un endpoint propio sin el envoltorio con CSRF.
    fetchs_directos = [line.strip() for line in js.splitlines()
                       if "fetch(" in line and "/api/" in line]
    assert not fetchs_directos, f"fetch sin csrfFetch: {fetchs_directos}"


def test_javascript_inyecta_el_token_en_el_formulario_de_cancelacion():
    js = _js()
    assert "name=\"csrf_token\"" in js, "el formulario de cancelar reserva se crea sin token"
    assert "bookings/${b.id}/cancel" in js


def test_ventana_de_permisos_refleja_la_matriz(client, store, login_as):
    """DDN_PERMS debe coincidir con la matriz, no Ampliarla."""
    login_as(client, CLIENT_EMAIL)
    html = client.get("/client-portal").get_data(as_text=True)
    bloque = re.search(r"window\.DDN_PERMS = (\{.*?\});", html, re.S)
    assert bloque, "falta window.DDN_PERMS en base.html"
    permisos = json.loads(bloque.group(1))
    assert permisos["bookings:create"] is True, "el cliente puede reservar para si mismo"
    assert permisos["bookings:status"] is False, "el cliente no cambia estados"
    assert permisos["audit:view"] is False
    assert permisos["data:reset"] is False
    assert permisos["clients:view"] is False


def test_post_sin_token_csrf_es_rechazado(client, store, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    propia = store.bookings[0]
    response = client.post(f"/bookings/{propia.id}/cancel", data={"reason": "sin token"})
    assert response.status_code == 400
    assert propia.status != "Cancelada", "la reserva se cancelo sin token CSRF"


def test_post_json_sin_cabecera_csrf_es_rechazado(client, store, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    response = client.post("/api/ai/recommendations", json={"budget": 1000})
    assert response.status_code == 400


def test_post_json_con_cabecera_csrf_pasa(client, store, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    token = client.get("/dashboard").get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', token).group(1)
    response = client.post("/api/ai/recommendations", json={"budget": 1000},
                           headers={"X-CSRFToken": token})
    assert response.status_code in (200, 422, 500), "el token deberia aceptarse"
