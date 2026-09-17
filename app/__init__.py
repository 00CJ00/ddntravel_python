"""Fábrica de la aplicación Flask para DDN Travel."""
import os
from flask import Flask
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# In development, always prefer the current local .env over stale shell values.
load_dotenv(override=True)


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


def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    # Trust the single reverse proxy used by ngrok for public OAuth callbacks.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    # An empty SECRET_KEY in .env must not disable Flask sessions.
    app.secret_key = os.environ.get("SECRET_KEY") or "ddn-travel-dev-secret-key"

    app.jinja_env.filters["usd"] = usd_filter
    app.jinja_env.filters["usd2"] = usd2_filter

    from . import routes
    app.register_blueprint(routes.bp)

    return app
