"""Matriz HTTP ruta × rol: el requisito central de la fase P1.

Para cada ruta de lectura se comprueba el código esperado según el rol y, sobre
todo, que ninguna respuesta sea 500 (un error de plantilla o de lógica no puede
escapar como "error del servidor").
"""
from __future__ import annotations

import pytest

from conftest import ADMIN_EMAIL, CLIENT_EMAIL, EMPLOYEE_EMAIL, login_as

# ruta -> (admin, employee, client). 200 = permitido; 403 = sin permiso;
# 302 = redirección (login o índice). Nunca debe haber 500.
MATRIZ_RUTAS = [
    ("/", 302, 302, 302),
    ("/dashboard", 200, 200, 403),
    ("/audit", 200, 403, 403),
    ("/clients", 200, 200, 403),
    ("/bookings", 200, 200, 403),
    ("/payments", 200, 200, 403),
    ("/promotions", 200, 200, 403),
    ("/documents", 200, 200, 200),
    ("/packages", 200, 200, 200),
    ("/destinations", 200, 200, 200),
    ("/hotels", 200, 200, 403),
    ("/flights", 200, 200, 403),
    ("/transports", 200, 200, 403),
    ("/activities", 200, 200, 200),
    ("/ai-predictive", 200, 200, 200),
    # El portal es exclusivo del cliente: el personal recibe 403, no redirección.
    ("/client-portal", 403, 403, 200),
    ("/edit-profile", 200, 200, 200),
    ("/contacto", 200, 200, 200),
    ("/api/health", 200, 200, 200),
]

ROLES = [("admin", ADMIN_EMAIL), ("employee", EMPLOYEE_EMAIL), ("client", CLIENT_EMAIL)]


@pytest.mark.parametrize("ruta,esperado_admin,esperado_employee,esperado_client", MATRIZ_RUTAS)
def test_matriz_http_por_rol(client, store, login_as, ruta, esperado_admin, esperado_employee, esperado_client):
    esperados = {"admin": esperado_admin, "employee": esperado_employee, "client": esperado_client}
    for rol, correo in ROLES:
        # Cada rol necesita su propia sesion: se usa un cliente nuevo por rol.
        with client.application.test_client() as sesion:
            login_as(sesion, correo)
            respuesta = sesion.get(ruta)
            codigo = respuesta.status_code
        assert codigo != 500, f"{rol} -> {ruta} devolvio 500"
        assert codigo == esperados[rol], f"{rol} -> {ruta} devolvio {codigo}, se esperaba {esperados[rol]}"


def test_sin_sesion_todo_redirige_al_login(client, store):
    """Ninguna ruta privada responde con datos a un visitante anónimo."""
    for ruta, *_ in MATRIZ_RUTAS:
        if ruta in ("/api/health", "/contacto", "/"):
            continue
        respuesta = client.get(ruta)
        assert respuesta.status_code in (302, 400), f"{ruta} -> {respuesta.status_code}"
        if respuesta.status_code == 302:
            assert "/login" in respuesta.headers["Location"], ruta


def test_escalada_via_switch_user_ya_no_existe(client, store, login_as):
    """La escalada de privilegios del P0 se cerró eliminando la ruta."""
    assert client.post("/switch-user", data={"user_id": "usr-admin"}).status_code in (404, 405)
    reglas = {r.rule for r in client.application.url_map.iter_rules()}
    assert "/switch-user" not in reglas


def test_ningun_endpoint_json_devuelve_500(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    import re
    html = client.get("/dashboard").get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', html).group(1)
    endpoints = [r.rule for r in client.application.url_map.iter_rules()
                 if r.rule.startswith("/api/")]
    for ruta in endpoints:
        respuesta = client.post(ruta, json={}, headers={"X-CSRFToken": token})
        assert respuesta.status_code != 500, f"POST {ruta} devolvio 500"
