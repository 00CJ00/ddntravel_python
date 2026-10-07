"""Comandos de la CLI de Flask para DDN Travel (fase P2).

Se registran en la fábrica (``create_app``) para que ``flask seed`` y
``flask backup`` estén disponibles desde la raíz del proyecto.
``flask db ...`` lo aporta Flask-Migrate.
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


@click.command("backup")
@click.option("--dir", "backup_dir", type=click.Path(file_okay=False),
              help="Carpeta donde escribir los respaldos (por defecto BACKUP_DIR).")
@click.option("--keep", type=int, default=None,
              help="Cuántos respaldos recientes conservar (por defecto BACKUP_KEEP).")
@click.option("--restore", "restore_file", metavar="ARCHIVO", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Restaura este respaldo en lugar de crear uno nuevo.")
@with_appcontext
def backup_command(backup_dir, keep, restore_file) -> None:
    """Crea un respaldo de la base de datos (SQLite o PostgreSQL).

    Sin argumentos copia la base a ``backups/`` con marca de tiempo y conserva
    solo los ``BACKUP_KEEP`` más recientes. Con ``--restore`` sustituye la base
    actual por el archivo indicado, tras verificar que el respaldo es íntegro y
    contiene el esquema esperado.
    """
    from .backup import (
        BackupError,
        create_backup,
        resolve_settings,
        restore_backup,
    )

    try:
        settings = resolve_settings(current_app, backup_dir=backup_dir, keep=keep)
        if restore_file:
            copia_previa = restore_backup(restore_file, settings=settings)
            click.echo(f"Base de datos restaurada desde {restore_file}.")
            if copia_previa:
                click.echo(f"Copia de la base anterior: {copia_previa}")
        else:
            destino = create_backup(settings=settings)
            click.echo(f"Respaldo creado: {destino}")
    except BackupError as exc:
        raise click.ClickException(str(exc)) from exc
