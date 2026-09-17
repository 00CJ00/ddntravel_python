"""Tests de la capa web: login, protección de rutas por rol y manejo de errores."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.store as store_module
from app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "STATE_PATH", tmp_path / "state.json")
    store_module.store = store_module.DataStore()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "ddn123"},
                       follow_redirects=False)


def test_sin_login_redirect_a_login(client):
    res = client.get("/dashboard")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_login_credenciales_incorrectas(client):
    res = client.post("/login", data={"email": "admin@ddntravel.com", "password": "mala"})
    assert res.status_code == 200
    assert "Contraseña" in res.get_data(as_text=True)


def test_login_admin_ok(client):
    res = _login(client, "admin@ddntravel.com")
    assert res.status_code == 302
    assert "/dashboard" in res.headers["Location"]


def test_login_agente_ok(client):
    res = _login(client, "sofia.v@ddntravel.com")
    assert res.status_code == 302


def test_admin_puede_ver_auditoria(client):
    _login(client, "admin@ddntravel.com")
    res = client.get("/audit")
    assert res.status_code == 200


def test_agente_no_puede_ver_auditoria(client):
    _login(client, "sofia.v@ddntravel.com")
    res = client.get("/audit")
    assert res.status_code == 403


def test_cliente_no_puede_ver_reservas(client):
    _login(client, "roberto.gomez@gmail.com")
    res = client.get("/bookings")
    assert res.status_code == 403


def test_cliente_si_puede_ver_su_portal(client):
    _login(client, "roberto.gomez@gmail.com")
    res = client.get("/client-portal")
    assert res.status_code == 200


def test_pagina_404(client):
    res = client.get("/ruta-que-no-existe")
    assert res.status_code == 404
    assert "no existe" in res.get_data(as_text=True)


def test_logout_limpia_sesion(client):
    _login(client, "admin@ddntravel.com")
    client.post("/logout")
    res = client.get("/dashboard")
    assert res.status_code == 302