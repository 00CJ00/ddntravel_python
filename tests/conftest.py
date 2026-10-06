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
from flask import g
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.store as store_module  # noqa: E402
from app import create_app, seed as seed_module  # noqa: E402
from app.config import DevelopmentConfig  # noqa: E402
from app.extensions import db  # noqa: E402

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
    # Base de datos aislada por prueba, en memoria y compartida entre conexiones.
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }


class TestingConfigRateLimit(TestingConfig):
    """ Igual que ``TestingConfig`` pero con el rate limiting activo. """

    RATELIMIT_ENABLED = True


@pytest.fixture
def app():
    """Aplicación de pruebas con base de datos en memoria sembrada.

    El contexto de aplicación se mantiene durante toda la prueba para que la
    sesión de SQLAlchemy sea la misma en los accesos directos al ``store`` y en
    las peticiones HTTP del cliente de pruebas.
    """
    application = create_app(TestingConfig)
    ctx = application.app_context()
    ctx.push()
    db.drop_all()
    db.create_all()
    seed_module.seed_database(reset=True)

    # El contexto de aplicación vive durante toda la prueba (para que el
    # ``store`` y las peticiones compartan la misma sesión de SQLAlchemy).
    # Como ``g`` es por contexto (no por petición), Flask-WTF cachearía el token
    # CSRF y su validación entre peticiones; se limpia al iniciar cada una.
    def _limpiar_csrf_en_g():
        g.pop("csrf_token", None)
        g.pop("csrf_valid", None)

    application.before_request_funcs.setdefault(None, []).insert(0, _limpiar_csrf_en_g)

    try:
        yield application
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


@pytest.fixture
def store(app):
    """Instancia global del ``DataStore`` sobre la BD de la prueba."""
    return store_module.store


@pytest.fixture
def make_app():
    """Factoría de aplicaciones con configuración de pruebas."""
    def _factory(config_object=TestingConfig, **overrides):
        application = create_app(config_object)
        application.config.update(overrides)
        return application
    return _factory


@pytest.fixture
def client(app):
    """Cliente HTTP de pruebas."""
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def client_ratelimit(make_app):
    """Cliente HTTP con el rate limiting activo, sobre una app aislada."""
    application = make_app(TestingConfigRateLimit)
    ctx = application.app_context()
    ctx.push()
    db.drop_all()
    db.create_all()
    seed_module.seed_database(reset=True)

    def _limpiar_csrf_en_g():
        g.pop("csrf_token", None)
        g.pop("csrf_valid", None)

    application.before_request_funcs.setdefault(None, []).insert(0, _limpiar_csrf_en_g)

    try:
        with application.test_client() as test_client:
            yield test_client
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


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


def client_booking_of(store, email: str):
    """Devuelve la primera reserva perteneciente al cliente con ese correo."""
    return next(b for b in store.bookings if b.client_email == email)


@pytest.fixture
def post_csrf():
    """Devuelve la función :func:`post_form` como fixture."""
    return post_form


@pytest.fixture
def login_as():
    """Devuelve la función :func:`login` como fixture."""
    return login
