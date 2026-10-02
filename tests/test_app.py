"""Tests de la capa web: login, protección de rutas por rol y manejo de errores.

Las fixtures (``client``, ``store``, ``login_as``) viven en ``tests/conftest.py``
para que la suite sea homogénea y el estado quede siempre aislado.
"""


def _login(client, login_as, email):
    return login_as(client, email)


def test_sin_login_redirect_a_login(client):
    res = client.get("/dashboard")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_login_credenciales_incorrectas(client, post_csrf):
    res = post_csrf(client, "/login", {"email": "admin@ddntravel.com", "password": "mala"})
    assert res.status_code == 200
    assert "Contraseña" in res.get_data(as_text=True)


def test_login_admin_ok(client, login_as):
    # POST /login redirige a "/" (main.index) y ese endpoint redirige a /dashboard.
    res = _login(client, login_as, "admin@ddntravel.com")
    assert res.status_code == 302
    assert res.headers["Location"] == "/"
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 302
    assert "/dashboard" in res.headers["Location"]


def test_login_agente_ok(client, login_as):
    res = _login(client, login_as, "sofia.v@ddntravel.com")
    assert res.status_code == 302


def test_admin_puede_ver_auditoria(client, login_as):
    _login(client, login_as, "admin@ddntravel.com")
    res = client.get("/audit")
    assert res.status_code == 200


def test_agente_no_puede_ver_auditoria(client, login_as):
    _login(client, login_as, "sofia.v@ddntravel.com")
    res = client.get("/audit")
    assert res.status_code == 403


def test_cliente_no_puede_ver_reservas(client, login_as):
    _login(client, login_as, "roberto.gomez@gmail.com")
    res = client.get("/bookings")
    assert res.status_code == 403


def test_cliente_si_puede_ver_su_portal(client, login_as):
    _login(client, login_as, "roberto.gomez@gmail.com")
    res = client.get("/client-portal")
    assert res.status_code == 200


def test_pagina_404(client):
    res = client.get("/ruta-que-no-existe")
    assert res.status_code == 404
    assert "no existe" in res.get_data(as_text=True)


def test_logout_limpia_sesion(client, login_as, post_csrf):
    _login(client, login_as, "admin@ddntravel.com")
    post_csrf(client, "/logout", csrf_from="/dashboard")
    res = client.get("/dashboard")
    assert res.status_code == 302
