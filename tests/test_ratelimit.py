"""Pruebas del paso 8: rate limiting, límites de entrada y sesión.

Comprueba que los límites de la configuración realmente se aplican (429), que
el login no filtra si el correo existe y que el chat no hace coincidencia por
subcadenas.
"""
from __future__ import annotations

import pytest

from conftest import (
    ADMIN_EMAIL, CLIENT_EMAIL, DEMO_PASSWORD, EMPLOYEE_EMAIL, login_as,
    post_form, read_csrf_token,
)

# ----------------------------------------------------------------------
# Rate limiting
# ----------------------------------------------------------------------
def test_login_se_bloquea_tras_varios_intentos(client_ratelimit, store):
    """5/min por IP+correo: el sexto intento devuelve 429."""
    token = read_csrf_token(client_ratelimit, "/login")
    codigos = []
    for _ in range(8):
        respuesta = client_ratelimit.post("/login", data={
            "email": "atacante@example.com", "password": "incorrecta",
            "csrf_token": token,
        })
        codigos.append(respuesta.status_code)
    assert 429 in codigos, f"el login nunca devolvio 429 (codigos: {codigos})"


def test_login_exito_no_consume_el_limite_del_ataque(client_ratelimit, store):
    """El límite es por IP+correo: atacar a uno no bloquea a otro usuario."""
    token = read_csrf_token(client_ratelimit, "/login")
    for _ in range(7):
        client_ratelimit.post("/login", data={
            "email": "atacante@example.com", "password": "x", "csrf_token": token,
        })
    respuesta = client_ratelimit.post("/login", data={
        "email": ADMIN_EMAIL, "password": DEMO_PASSWORD, "csrf_token": token,
    })
    assert respuesta.status_code == 302, "un intento legitimo fue bloqueado por el de otro"


def test_get_login_no_consume_el_limite(client_ratelimit, store):
    """El límite es solo de POST: cargar el formulario nunca se bloquea."""
    for _ in range(10):
        assert client_ratelimit.get("/login").status_code == 200


def test_chat_tiene_limite(client_ratelimit, store, login_as):
    login_as(client_ratelimit, EMPLOYEE_EMAIL)
    codigos = set()
    for i in range(40):
        token = read_csrf_token(client_ratelimit, "/dashboard")
        respuesta = client_ratelimit.post("/api/chat/message",
                                          json={"message": f"consulta numero {i}"},
                                          headers={"X-CSRFToken": token})
        codigos.add(respuesta.status_code)
    assert 429 in codigos, f"el chat nunca devolvio 429 (codigos: {codigos})"


# ----------------------------------------------------------------------
# Limites de longitud
# ----------------------------------------------------------------------
def test_chat_rechaza_mensajes_largos(client, store, login_as):
    login_as(client, CLIENT_EMAIL)
    token = read_csrf_token(client, "/client-portal")
    respuesta = client.post("/api/chat/message",
                            json={"message": "a" * 5000},
                            headers={"X-CSRFToken": token})
    assert respuesta.status_code == 422


def test_chat_acepta_mensajes_normales(client, store, login_as):
    login_as(client, CLIENT_EMAIL)
    token = read_csrf_token(client, "/client-portal")
    respuesta = client.post("/api/chat/message",
                            json={"message": "¿Cómo hago una reserva?"},
                            headers={"X-CSRFToken": token})
    assert respuesta.status_code == 200
    assert respuesta.get_json()["faq"] is True


def test_contacto_rechaza_mensajes_largos(client, store):
    respuesta = post_form(client, "/contacto", {
        "name": "Visitante", "email": "v@example.com", "subject": "Hola",
        "message": "a" * 2500,
    })
    assert respuesta.status_code == 200
    assert "demasiado largo" in respuesta.get_data(as_text=True)


def test_contacto_acepta_mensajes_validos(client, store):
    respuesta = post_form(client, "/contacto", {
        "name": "Visitante", "email": "v@example.com", "subject": "Consulta",
        "message": "Quisiera información sobre un paquete a Punta Cana.",
    })
    assert respuesta.status_code == 302
    assert store.notifications, "el mensaje deberia registrarse como notificacion"


def test_contacto_sin_mensaje_no_rompe(client, store):
    """El POST automatizado sin 'message' no debe lanzar KeyError (bug P1)."""
    respuesta = post_form(client, "/contacto", {"name": "Visitante"})
    assert respuesta.status_code == 200
    assert "Escribe tu mensaje" in respuesta.get_data(as_text=True)


# ----------------------------------------------------------------------
# Coincidencia del chat por palabras completas
# ----------------------------------------------------------------------
@pytest.mark.parametrize("mensaje,debe_ser_faq", [
    ("¿Cómo hago una reserva?", True),
    ("quiero itinerarios para la playa", True),   # palabra completa de la FAQ
    ("estoy en which?", False),                   # "hi" dentro de "which"
    ("aholah", False),                            # contiene "hola" pero no es el saludo
    ("hola", False),                              # saludo, no FAQ
])
def test_chat_no_hace_coincidencia_por_subcadena(client, store, login_as, mensaje, debe_ser_faq):
    login_as(client, CLIENT_EMAIL)
    token = read_csrf_token(client, "/client-portal")
    respuesta = client.post("/api/chat/message", json={"message": mensaje},
                            headers={"X-CSRFToken": token})
    assert respuesta.status_code == 200
    assert respuesta.get_json()["faq"] is debe_ser_faq


# ----------------------------------------------------------------------
# Sesion y cookies
# ----------------------------------------------------------------------
def test_sesion_dura_ocho_horas(app):
    from datetime import timedelta
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=8)
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_cookie_de_sesion_no_es_accesible_desde_javascript(client, store, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    respuesta = client.get("/dashboard")
    cookies = respuesta.headers.getlist("Set-Cookie")
    assert any("HttpOnly" in c for c in cookies), cookies
    assert all("SameSite=Lax" in c for c in cookies if "ddn" in c.lower()), cookies


# ----------------------------------------------------------------------
# Paginas publicas sin sesion (base.html no debe romper)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("ruta", ["/login", "/contacto", "/api/health"])
def test_paginas_publicas_sin_sesion(client, store, ruta):
    respuesta = client.get(ruta)
    assert respuesta.status_code == 200, f"{ruta} devolvio {respuesta.status_code}"


def test_login_no_filtra_si_el_correo_existe(client, store):
    """El mensaje es idéntico exista o no el correo (anti enumeración)."""
    existente = post_form(client, "/login", {"email": ADMIN_EMAIL, "password": "mala"})
    inexistente = post_form(client, "/login", {"email": "nadie@example.com", "password": "mala"})
    assert "incorrectos" in existente.get_data(as_text=True)
    assert "incorrectos" in inexistente.get_data(as_text=True)
