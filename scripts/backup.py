"""Respaldo y restauración de la base de datos de DDN Travel.

Uso desde la raíz del proyecto (sin necesidad del contexto de Flask)::

    python scripts/backup.py                  # crea un respaldo en backups/
    python scripts/backup.py --keep 20        # conserva los 20 más recientes
    python scripts/backup.py --dir /tmp/copia # otra carpeta de destino
    python scripts/backup.py --list           # lista los respaldos existentes
    python scripts/backup.py --restore backups/ddn-20261002-120000.db

El comando equivalente dentro de Flask es ``flask backup`` (con las mismas
opciones). La implementación vive en :mod:`app.backup`.

Advertencia sobre el camino PostgreSQL: usa ``pg_dump``/``pg_restore`` y está
escrito pero **sin probar en este entorno**, porque no hay servidor PostgreSQL
ni driver configurados (el driver se instala en la fase P9). El camino SQLite
sí está cubierto por pruebas reales en ``tests/test_backup.py``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permite ejecutar el script directamente desde la raíz del proyecto.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Import deliberadamente después de ajustar sys.path para poder ejecutarlo
# directamente (``python scripts/backup.py``) desde la raíz del proyecto.
from app.backup import (
    BackupError,
    create_backup,
    list_backups,
    resolve_settings,
    restore_backup,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Respalda o restaura la base de datos de DDN Travel.")
    parser.add_argument("--dir", dest="backup_dir",
                        help="Carpeta donde escribir los respaldos.")
    parser.add_argument("--keep", type=int,
                        help="Cuántos respaldos recientes conservar.")
    parser.add_argument("--restore", metavar="ARCHIVO",
                        help="Restaura este respaldo en vez de crear uno.")
    parser.add_argument("--list", action="store_true",
                        help="Lista los respaldos existentes y termina.")
    args = parser.parse_args(argv)

    settings = resolve_settings(backup_dir=args.backup_dir, keep=args.keep)

    try:
        if args.list:
            archivos = list_backups(settings.backup_dir)
            if not archivos:
                print(f"No hay respaldos en {settings.backup_dir}.")
            for archivo in archivos:
                print(archivo)
            return 0

        if args.restore:
            copia_previa = restore_backup(args.restore, settings=settings)
            print(f"Base de datos restaurada desde {args.restore}.")
            if copia_previa:
                print(f"Copia de la base anterior: {copia_previa}")
            return 0

        destino = create_backup(settings=settings)
        print(f"Respaldo creado: {destino}")
        return 0
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())