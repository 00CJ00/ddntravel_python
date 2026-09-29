"""Fixtures compartidas por la suite de pruebas de DDN Travel.

Objetivos de este módulo:

1. Aislar el ``DataStore`` para que ninguna prueba toque ``app/state.json``.
2. Crear la aplicación con una configuración determinista (SECRET_KEY fija,
   CSRF activado, rate limiting desactivado salvo donde se prueba).
3. Ofrecer utilidades reutilizables para iniciar sesión y enviar formularios
   con el token CSRF, evitando repetir ese código en cada test.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.routes as routes_module  # noqa: E402
import app.store as store_module  # noqa: E402
from app import create_app  # noqa: E402
from app.config import DevelopmentConfig  # noqa: E402

# El token CSRF que Flask-WTF inserta en los formularios.
CSRF_INPUT_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')

# Credenciales de demostración sembradas en app/seed_data.json.
ADMIN_EMAIL = "admin@ddntravel.com"
EMPLOYEE_EMAIL = "sofia.v@ddntravel.com"
CLIENT_EMAIL = "roberto.gomez@gmail.com"
DEMO_PASSWORD = "ddn123"


class TestingConfig(DevelopmentConfig):
    """Configuración determinista para las pruebas."""

    ENV = "development"
    DEBUG = False
    TESTING = True
    SECRET_KEY = "clave-privada-de-pruebas-ddn-travel-0000000000"
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    RATELIMIT_ENABLED = False
    ENABLE_RESET = "0"
    ENABLE_DEV_SWITCH = "0"


class TestingConfigRateLimit(TestingConfig):
    """ Igual que ``TestingConfig`` pero con el rate limiting activo. """

    RATELIMIT_ENABLED = True


@pytest.fixture
def store(tmp_path, monkeypatch):
    """DataStore limpio a partir de la semilla, sin tocar el estado real."""
    monkeypatch.setattr(store_module, "STATE_PATH", tmp_path / "state.json")
    st = store_module.DataStore()
    st.reset_all_data(log=False)
    # Los módulos que hacen ``from .store import store`` guardan su propia
    # referencia; se redirigen todas para que las pruebas sean aisladas.
    for module in (store_module, routes_module):
        monkeypatch.setattr(module, "store", st, raising=False)
    return st


@pytest.fixture
def make_app(store):
    """Factoría de aplicaciones con configuración de pruebas."""
    def _factory(config_object=TestingConfig, **overrides):
        app = create_app(config_object)
        app.config.update(overrides)
        return app
    return _factory


@pytest.fixture
def app(make_app):
    """Aplicación de pruebas (CSRF activo, sin rate limiting)."""
    return make_app()


@pytest.fixture
def client(app):
    """Cliente HTTP de pruebas."""
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def client_ratelimit(make_app):
    """Cliente HTTP con el rate limiting activo (para probar /login)."""
    with make_app(TestingConfigRateLimit).test_client() as test_client:
        yield test_client


# ----------------------------------------------------------------------
# Utilidades reutilizables
# ----------------------------------------------------------------------
def read_csrf_token(client, url: str = "/login") -> str:
    """Lee el token CSRF que la aplicación renderiza en un formulario.

    El token vive en la sesión, así que si la página indicada todavía no tiene
    ningún formulario (tareas anteriores a la fase P1) se recurre al login,
    que siempre lo incluye.
    """
    html = client.get(url).get_data(as_text=True)
    match = CSRF_INPUT_RE.search(html)
    if match:
        return match.group(1)
    html = client.get("/login").get_data(as_text=True)
    match = CSRF_INPUT_RE.search(html)
    assert match, f"No se encontró el token CSRF en {url} ni en /login"
    return match.group(1)


def post_form(client, url: str, data: dict | None = None, *, csrf_from: str = "/login", **kwargs):
    """Envía un formulario POST incluyendo un token CSRF válido."""
    payload = dict(data or {})
    payload["csrf_token"] = read_csrf_token(client, csrf_from)
    return client.post(url, data=payload, **kwargs)


def login(client, email: str, password: str = DEMO_PASSWORD):
    """Inicia sesión como el usuario indicado y devuelve la respuesta del POST."""
    return post_form(client, "/login", {"email": email, "password": password})


@pytest.fixture
def post_csrf():
    """Devuelve la función :func:`post_form` como fixture."""
    return post_form


@pytest.fixture
def login_as():
    """Devuelve la función :func:`login` como fixture."""
    return login
