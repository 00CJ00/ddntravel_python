"""Extensiones de Flask compartidas por la aplicación.

Se declaran aquí (y no dentro de ``create_app``) para que las rutas puedan
importar los objetos y usar sus decoradores, por ejemplo
``@limiter.limit("5 per minute")`` en el login, sin importar la fábrica de la
aplicación y provocar una importación circular.
"""
from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

#: Protección CSRF de todos los formularios y peticiones fetch de la app.
csrf = CSRFProtect()

#: Limitador de peticiones por IP (anti fuerza bruta y anti abuso).
limiter = Limiter(key_func=get_remote_address, default_limits=[])

#: ORM de la aplicación (SQLAlchemy). Sustituye al antiguo ``state.json``.
db = SQLAlchemy()

#: Migraciones de esquema (Alembic) gestionadas con ``flask db ...``.
migrate = Migrate()
