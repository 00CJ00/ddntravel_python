"""Punto de entrada de la aplicación DDN Travel.

HOST y PORT se leen de las variables de entorno (por defecto 127.0.0.1:3000).
El modo debug solo se activa si FLASK_DEBUG=1.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"],
            debug=app.config.get("DEBUG", False))