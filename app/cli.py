"""Comandos de la CLI de Flask para DDN Travel (fase P2).

Se registran en la fábrica (``create_app``) para que ``flask seed`` esté
disponible desde la raíz del proyecto. ``flask db ...`` lo aporta Flask-Migrate.
"""
from __future__ import annotations

import click
from flask import current_app
from flask.cli import with_appcontext


@click.command("seed")
@click.option("--reset", is_flag=True,
              help="Vacía la base de datos antes de sembrar (solo desarrollo).")
@with_appcontext
def seed_command(reset: bool) -> None:
    """Carga ``app/seed_data.json`` de forma idempotente.

    Sin ``--reset`` no duplica datos: si ya hay usuarios no hace nada. Con
    ``--reset`` vacía primero las tablas, pero solo se permite en desarrollo
    (``FLASK_ENV=development``); en producción el comando falla.
    """
    from . import seed as seed_module

    if reset and current_app.config.get("ENV") != "development":
        raise click.ClickException(
            "--reset solo está permitido en desarrollo (FLASK_ENV=development).")

    seeded = seed_module.seed_database(reset=reset)
    if seeded:
        click.echo("Datos de demostración cargados correctamente.")
    else:
        click.echo("La base de datos ya contiene datos; no se modificó nada. "
                   "Usa --reset en desarrollo para recargarla.")
