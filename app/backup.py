"""Respaldo y restauración de la base de datos (P2, paso 9).

Dos motores, un mismo contrato:

- **SQLite**: se usa ``sqlite3.Connection.backup()``, que produce una copia
  consistente aunque la base esté en uso (copia página a página dentro de una
  transacción). Este camino está cubierto por pruebas reales: se crea un
  respaldo, se verifica que el archivo resultante es una base funcional y se
  restaura.
- **PostgreSQL**: se delega en las utilidades oficiales ``pg_dump`` (formato
  ``custom``) y ``pg_restore``. En este entorno **no hay PostgreSQL
  configurado y el driver se instala en la fase P9**, así que este camino está
  escrito pero **sin probar contra una base real**: queda pendiente de
  verificación cuando P9 configure ``DATABASE_URL``.

Los respaldos se escriben en ``BACKUP_DIR`` (``backups/`` por defecto, carpeta
ignorada por git) con una marca de tiempo, y solo se conservan los ``BACKUP_KEEP``
más recientes.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from .config import BASE_DIR, DEFAULT_DATABASE_URI

#: Formato de la marca de tiempo en el nombre de los archivos.
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

#: Sufijo de los respaldos de cada motor.
SQLITE_SUFFIX = ".db"
POSTGRES_SUFFIX = ".dump"


class BackupError(Exception):
    """Error de respaldo/restauración con un mensaje apto para la consola."""


@dataclass(frozen=True)
class BackupSettings:
    """Resuelve los tres datos que gobiernan un respaldo."""

    database_uri: str
    backup_dir: Path
    keep: int = 10

    @property
    def backend(self) -> str:
        """Nombre del motor de la URI configurada (``sqlite``/``postgresql``)."""
        return make_url(self.database_uri).get_backend_name()


def resolve_settings(app=None, backup_dir=None, keep=None) -> BackupSettings:
    """Obtiene la configuración de respaldo desde la app, el entorno o la config.

    Si se pasa ``app`` (o hay contexto de aplicación activo) se leen sus valores;
    si no, se usan las variables de entorno con los mismos valores por defecto
    que :class:`app.config.Config`, de modo que el script también funciona fuera
    de Flask.
    """
    if app is None:
        try:
            from flask import current_app

            app = current_app._get_current_object()
        except RuntimeError:  # sin contexto de aplicación: se usan los valores por defecto
            app = None

    if app is not None:
        database_uri = app.config.get("SQLALCHEMY_DATABASE_URI") or DEFAULT_DATABASE_URI
        default_dir = app.config.get("BACKUP_DIR") or str(BASE_DIR / "backups")
        default_keep = app.config.get("BACKUP_KEEP", 10)
    else:
        database_uri = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URI
        default_dir = os.environ.get("BACKUP_DIR") or str(BASE_DIR / "backups")
        default_keep = int(os.environ.get("BACKUP_KEEP", "10"))

    return BackupSettings(
        database_uri=database_uri,
        backup_dir=Path(backup_dir) if backup_dir else Path(default_dir),
        keep=int(keep) if keep is not None else int(default_keep),
    )


def model_tables() -> list[str] | None:
    """Nombres de tabla de los modelos, o ``None`` si aún no hay ninguno.

    Sirve para comprobar que un respaldo contiene el esquema completo antes de
    sobrescribir la base de datos viva.
    """
    # Importar el paquete ``models`` es lo que registra las tablas en el
    # metadata de ``db``; por eso el import se descarta de forma explícita.
    from . import models  # noqa: F401
    from .extensions import db

    names = sorted(db.metadata.tables)
    return names or None


# ----------------------------------------------------------------------
# Utilidades de bajo nivel
# ----------------------------------------------------------------------
def sqlite_file_from_uri(uri: str) -> Path:
    """Extrae la ruta del archivo SQLite de una URI ``sqlite:///...``."""
    url = make_url(uri)
    if url.get_backend_name() != "sqlite":
        raise BackupError(f"La URI {uri!r} no corresponde a una base SQLite.")
    database = url.database
    if not database or database == ":memory:":
        raise BackupError(
            "No se puede respaldar una base SQLite en memoria: use un archivo.")
    return Path(database)


def verify_sqlite(path, expected_tables=None) -> set[str]:
    """Comprueba que ``path`` es una base SQLite íntegra y devuelve sus tablas.

    Lanza :class:`BackupError` si ``PRAGMA integrity_check`` falla o si faltan
    tablas esperadas, para no restaurar un archivo corrupto o de otro esquema.
    """
    path = Path(path)
    if not path.is_file():
        raise BackupError(f"No existe el archivo de respaldo: {path}")

    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"{path} no es una base SQLite legible: {exc}") from exc

    try:
        resultado = con.execute("PRAGMA integrity_check").fetchone()[0]
        tablas = {
            fila[0]
            for fila in con.execute(
                "select name from sqlite_master where type='table'")
        }
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"{path} no es una base SQLite válida: {exc}") from exc
    finally:
        con.close()

    if resultado != "ok":
        raise BackupError(
            f"La integridad de {path} es incorrecta ({resultado}): no se restaura.")

    faltan = set(expected_tables or ()) - tablas
    if faltan:
        raise BackupError(
            f"El respaldo {path.name} no contiene las tablas esperadas: "
            f"{sorted(faltan)}")

    return tablas


def _pg_dump_args(url, dest: Path) -> list[str]:
    """Argumentos de ``pg_dump`` para volcar ``url`` en el archivo ``dest``."""
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--host", url.host or "localhost",
        "--port", str(url.port or 5432),
        "--username", url.username or "postgres",
        "--dbname", url.database or "",
        "--file", str(dest),
    ]


def _pg_restore_args(url, source: Path) -> list[str]:
    """Argumentos de ``pg_restore`` para restaurar ``source`` sobre ``url``."""
    return [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--host", url.host or "localhost",
        "--port", str(url.port or 5432),
        "--username", url.username or "postgres",
        "--dbname", url.database or "",
        str(source),
    ]


def _pg_env(url) -> dict[str, str]:
    """Entorno para ``pg_dump``/``pg_restore`` (la contraseña va en PGPASSWORD)."""
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


# ----------------------------------------------------------------------
# Respaldo
# ----------------------------------------------------------------------
def _copy_sqlite(source: Path, dest: Path) -> None:
    """Copia la base SQLite con ``Connection.backup()`` (copia consistente)."""
    origen = sqlite3.connect(source)
    try:
        destino = sqlite3.connect(dest)
        try:
            origen.backup(destino)
        finally:
            destino.close()
    finally:
        origen.close()


def _run_pg(args: list[str], env: dict[str, str]) -> None:
    """Ejecuta una utilidad de PostgreSQL y traduce su fallo a BackupError."""
    executable = args[0]
    if shutil.which(executable) is None:
        raise BackupError(
            f"{executable} no está instalado o no está en el PATH; no se puede "
            f"operar sobre una base PostgreSQL desde este equipo.")
    try:
        subprocess.run(args, env=env, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detalle = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise BackupError(f"{executable} falló: {detalle or exc}") from exc


def _create_sqlite_backup(settings: BackupSettings) -> Path:
    origen = sqlite_file_from_uri(settings.database_uri)
    if not origen.is_file():
        raise BackupError(
            f"La base de datos no existe todavía: {origen}. "
            f"Ejecute ``flask db upgrade`` antes de respaldar.")

    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.backup_dir / _name(SQLITE_SUFFIX)
    if dest.exists():
        dest.unlink()

    _copy_sqlite(origen, dest)
    # Un respaldo que no se puede abrir no sirve: se descarta en el acto.
    verify_sqlite(dest)
    return dest


def _create_postgres_backup(settings: BackupSettings) -> Path:
    """Volca PostgreSQL con ``pg_dump``.

    SIN PROBAR EN ESTE ENTORNO: no hay servidor PostgreSQL ni driver
    configurados (el driver se instala en P9). Debe verificarse cuando P9
    defina ``DATABASE_URL``.
    """
    url = make_url(settings.database_uri)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.backup_dir / _name(POSTGRES_SUFFIX)
    if dest.exists():
        dest.unlink()

    _run_pg(_pg_dump_args(url, dest), _pg_env(url))
    return dest


def _name(suffix: str) -> str:
    return f"ddn-{datetime.now().strftime(TIMESTAMP_FORMAT)}{suffix}"


def create_backup(settings=None, keep=None, backup_dir=None) -> Path:
    """Crea un respaldo de la base configurada y devuelve su ruta.

    ``keep`` y ``backup_dir`` sobrescriben los valores de la configuración.
    """
    if settings is None:
        settings = resolve_settings(backup_dir=backup_dir, keep=keep)
    elif keep is not None:
        settings = BackupSettings(settings.database_uri, settings.backup_dir, int(keep))
    elif backup_dir is not None:
        settings = BackupSettings(settings.database_uri, Path(backup_dir), settings.keep)

    if settings.backend.startswith("sqlite"):
        dest = _create_sqlite_backup(settings)
    elif settings.backend.startswith("postgresql"):
        dest = _create_postgres_backup(settings)
    else:
        raise BackupError(
            f"Respaldo no soportado para el motor {settings.backend!r}; "
            f"solo se admiten SQLite y PostgreSQL.")

    prune_backups(settings.backup_dir, settings.keep, protect={dest})
    return dest


# ----------------------------------------------------------------------
# Conservación y restauración
# ----------------------------------------------------------------------
def list_backups(backup_dir) -> list[Path]:
    """Respaldo de la carpeta, del más reciente al más antiguo."""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    archivos = [p for p in backup_dir.iterdir() if p.is_file() and p.name != "README.md"]
    return sorted(archivos, key=lambda p: p.name, reverse=True)


def prune_backups(backup_dir, keep: int, protect=()) -> list[Path]:
    """Deja solo los ``keep`` respaldos más recientes y devuelve los borrados.

    Los archivos de ``protect`` (el recién creado o el que se restaura) nunca se
    borran, aunque ``keep`` sea menor que el número de archivos.
    """
    if keep < 0:
        raise BackupError("BACKUP_KEEP no puede ser negativo.")
    protegidos = {Path(p).resolve() for p in protect}
    borrados: list[Path] = []
    for viejo in list_backups(backup_dir)[max(int(keep), 0):]:
        if viejo.resolve() in protegidos:
            continue
        viejo.unlink()
        borrados.append(viejo)
    return borrados


def _restore_sqlite(settings: BackupSettings, origen: Path) -> Path | None:
    """Sustituye la base SQLite viva por el contenido del respaldo.

    Antes de sobrescribir se guarda una copia de seguridad de la base actual
    (``pre-restore-*.db``) para poder deshacer la operación.
    """
    destino = sqlite_file_from_uri(settings.database_uri)
    verify_sqlite(origen, model_tables())

    copia_previa: Path | None = None
    if destino.is_file():
        settings.backup_dir.mkdir(parents=True, exist_ok=True)
        copia_previa = settings.backup_dir / f"pre-restore-{_timestamp()}{SQLITE_SUFFIX}"
        _copy_sqlite(destino, copia_previa)

    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origen, destino)
    # El archivo temporal evita dejar la base a medias si algo falla al copiar.
    return copia_previa


def _restore_postgres(settings: BackupSettings, origen: Path) -> None:
    """Restaura con ``pg_restore``.

    SIN PROBAR EN ESTE ENTORNO: no hay servidor PostgreSQL ni driver
    configurados (el driver se instala en P9). Debe verificarse cuando P9
    defina ``DATABASE_URL``.
    """
    url = make_url(settings.database_uri)
    if not origen.is_file():
        raise BackupError(f"No existe el archivo de respaldo: {origen}")
    _run_pg(_pg_restore_args(url, origen), _pg_env(url))


def _timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def restore_backup(archivo, settings=None, keep=None, backup_dir=None) -> Path | None:
    """Restaura un respaldo previo sobre la base configurada.

    Devuelve la ruta de la copia de seguridad creada antes de sobrescribir (o
    ``None`` si la base no existía). Lanza :class:`BackupError` si el archivo no
    es un respaldo válido de este esquema.
    """
    origen = Path(archivo)
    if settings is None:
        settings = resolve_settings(backup_dir=backup_dir, keep=keep)
    verify_sqlite_or_pg_dump(origen, settings)

    copia_previa: Path | None
    if settings.backend.startswith("sqlite"):
        copia_previa = _restore_sqlite(settings, origen)
    elif settings.backend.startswith("postgresql"):
        _restore_postgres(settings, origen)
        copia_previa = None
    else:
        raise BackupError(
            f"Restauración no soportada para el motor {settings.backend!r}.")

    prune_backups(settings.backup_dir, settings.keep, protect={origen})
    return copia_previa


def verify_sqlite_or_pg_dump(origen: Path, settings: BackupSettings) -> None:
    """Valida el respaldo según el motor: SQLite se abre, pg_dump es un archivo."""
    if settings.backend.startswith("sqlite"):
        verify_sqlite(origen, model_tables())
        return
    # Formato custom de pg_dump: empieza por la firma PGDMP.
    with open(origen, "rb") as fh:
        firma = fh.read(5)
    if firma != b"PGDMP":
        raise BackupError(
            f"{origen} no parece un respaldo de PostgreSQL (firma PGDMP ausente).")