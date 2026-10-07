"""Punto de entrada WSGI para la CLI de Flask (``flask db ...``, ``flask seed``).

Flask descubre automáticamente este archivo, de modo que los comandos
``flask db upgrade`` y ``flask seed`` funcionan desde la raíz del proyecto
sin necesidad de definir ``FLASK_APP``.
"""
from app import create_app

app = create_app()
