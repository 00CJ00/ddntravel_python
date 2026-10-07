"""Pruebas de las migraciones Alembic (P2, paso 8).

Comprueban que ``flask db upgrade`` construye el esquema completo desde una base
vacía y que ``flask db downgrade base`` lo elimina, sobre una base SQLite en
disco. No se usa ``:memory:`` porque cada conexión vería una base distinta y las
migraciones no podrían verse entre pasos.
"""
from __future__ import annotations

import pytest
from flask import current_app
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect

from app import create_app
from app.config import DevelopmentConfig
from app.extensions import db


class MigrationConfig(DevelopmentConfig):
    """Configuración determinista para ejercitar las migraciones."""

    ENV = "development"
    DEBUG = False
    TESTING = True
    SECRET_KEY = "clave-privada-de-pruebas-ddn-travel-0000000000"
    RATELIMIT_ENABLED = False


@pytest.fixture
def migration_app(tmp_path):
    """App con una BD SQLite nueva en disco, lista para migrar desde cero."""
    db_path = (tmp_path / "migraciones.db").as_posix()

    # La URI debe fijarse ANTES de ``create_app``: Flask-SQLAlchemy crea el
    # motor durante ``init_app`` y no vuelve a leer la configuración después.
    class _MigrationConfig(MigrationConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    application = create_app(_MigrationConfig)

    ctx = application.app_context()
    ctx.push()
    try:
        yield application
    finally:
        db.session.remove()
        db.engine.dispose()
        ctx.pop()


def _tablas() -> set[str]:
    return set(inspect(db.engine).get_table_names())


def test_upgrade_desde_cero_crea_todo_el_esquema(migration_app):
    """Tras ``upgrade`` deben existir todas las tablas de los modelos."""
    esperadas = set(db.metadata.tables)

    assert _tablas() == set(), "la BD debe empezar vacía"

    upgrade()

    tablas = _tablas()
    assert "alembic_version" in tablas
    assert esperadas <= tablas, f"faltan tablas: {sorted(esperadas - tablas)}"


def test_downgrade_base_y_reaplicacion(migration_app):
    """``downgrade base`` vacía el esquema y ``upgrade`` lo reconstruye."""
    esperadas = set(db.metadata.tables)

    upgrade()
    assert esperadas <= _tablas()

    downgrade(revision="base")

    tablas_tras_bajar = _tablas()
    assert esperadas.isdisjoint(tablas_tras_bajar), (
        f"quedaron tablas: {sorted(esperadas & tablas_tras_bajar)}"
    )

    upgrade()
    assert esperadas <= _tablas(), "el esquema no se reconstruyó tras downgrade"


def test_render_as_batch_activo(migration_app):
    """SQLite necesita ``render_as_batch`` para los futuros ALTER TABLE."""
    config_args = current_app.extensions["migrate"].configure_args
    assert config_args.get("render_as_batch") is True
