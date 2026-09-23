"""Fábrica de la aplicación Flask para DDN Travel."""
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import get_config, resolve_secret_key


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

    from . import routes
    app.register_blueprint(routes.bp)

    return app