"""Fábrica de la aplicación Flask para DDN Travel."""
import os

from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import INSTANCE_DIR, get_config, resolve_secret_key
from .extensions import csrf, db, limiter, migrate


def usd_filter(value):
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return value


def usd2_filter(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return value


def create_app(config_object=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    # Trust the single reverse proxy used by ngrok for public OAuth callbacks.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    config = get_config() if config_object is None else config_object
    app.config.from_object(config)
    app.secret_key = resolve_secret_key(
        app.config.get("SECRET_KEY", "").strip(),
        app.config.get("ENV", "development"),
        logger=app.logger,
    )

    app.jinja_env.filters["usd"] = usd_filter
    app.jinja_env.filters["usd2"] = usd2_filter

    # --- Base de datos y migraciones (P2) ---
    # La carpeta instance/ guarda la BD SQLite de desarrollo.
    # Flask-SQLAlchemy crea una sesión por contexto de aplicación (es decir, por
    # petición) y la cierra en su teardown. El commit/rollback de dominio NO se
    # dispersa por las rutas: se centraliza en DataStore._commit/_rollback.
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    db.init_app(app)
    # render_as_batch=True: SQLite no soporta ALTER TABLE nativo para la mayoría
    # de cambios; el modo batch de Alembic los emula recreando la tabla. Se
    # necesita desde la primera migración para que las futuras (P3+) funcionen.
    migrate.init_app(app, db, render_as_batch=True)

    # --- Seguridad de formularios: toda ruta que muta datos exige token CSRF ---
    # Flask-WTF añade el global `csrf_token` a Jinja y acepta la cabecera
    # X-CSRFToken en las peticiones fetch (ver static/js/app.js).
    csrf.init_app(app)

    # --- Rate limiting por IP (anti fuerza bruta y anti abuso) ---
    limiter.init_app(app)

    from . import permissions
    # `can(permiso)` en las plantillas oculta botones que el usuario no puede
    # usar. La validación real siempre ocurre en la ruta (permission_required).
    app.jinja_env.globals["can"] = permissions.can

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error):
        """Respuesta 400 clara cuando falta o es inválido el token CSRF.

        No se redirige al login: el problema no es la sesión, es el token, y un
        302 ocultaría el ataque. La página de error invita a recargar.
        """
        if request.path.startswith("/api/"):
            return jsonify({"success": False,
                            "error": "Token CSRF inválido o ausente."}), 400
        return render_template(
            "error.html",
            code=400,
            message="La sesión expiró o el formulario es inválido. Recarga la página e inténtalo de nuevo.",
        ), 400

    from . import routes
    app.register_blueprint(routes.bp)

    # --- Comandos de la CLI (``flask seed``, ``flask backup``; ``flask db ...`` ---
    # lo aporta Flask-Migrate) ---
    from .cli import backup_command, seed_command
    app.cli.add_command(seed_command)
    app.cli.add_command(backup_command)

    return app
