"""Pruebas del respaldo y la restauración de la base de datos (P2, paso 9).

Cobertura:

- El camino **SQLite** se prueba de verdad: se genera un respaldo con
  ``Connection.backup()``, se comprueba que el archivo resultante es una base
  legible e íntegra, y se restaura para recuperar los datos originales.
- El comando ``flask backup`` (y su equivalente ``scripts/backup.py``) se
  ejercita sobre la aplicación con el esquema real creado por Alembic.
- El camino **PostgreSQL** (``pg_dump``/``pg_restore``) no puede probarse aquí
  porque este entorno no tiene servidor PostgreSQL ni driver (eso llega en P9).
  Se prueba solo la construcción de los argumentos, y el test que ejecutaría
  ``pg_dump`` se salta cuando la utilidad no está instalada.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from flask_migrate import upgrade

from app import backup as backup_module
from app import create_app
from app import seed as seed_module
from app.backup import (
    BackupError,
    BackupSettings,
    create_backup,
    list_backups,
    prune_backups,
    resolve_settings,
    restore_backup,
    verify_sqlite,
)
from app.config import DevelopmentConfig

RAIZ = Path(__file__).resolve().parent.parent


class BackupConfig(DevelopmentConfig):
    """Configuración determinista para los tests de respaldo."""

    ENV = "development"
    DEBUG = False
    TESTING = True
    SECRET_KEY = "clave-privada-de-pruebas-ddn-travel-0000000000"
    RATELIMIT_ENABLED = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False


def sqlite_file_from_uri(uri: str) -> Path:
    """Ruta del archivo SQLite que apunta una URI ``sqlite:///...``."""
    return Path(backup_module.make_url(uri).database)


def crear_sqlite(path: Path, filas) -> None:
    """Crea una base SQLite mínima con la tabla ``notas`` y las filas dadas."""
    con = sqlite3.connect(path)
    try:
        con.execute("create table notas (id integer primary key, texto text)")
        con.executemany("insert into notas (texto) values (?)", [(f,) for f in filas])
        con.commit()
    finally:
        con.close()


@pytest.fixture
def bd_simple(tmp_path, monkeypatch):
    """Base SQLite de dos filas y una carpeta de respaldos, aisladas del repo.

    ``model_tables`` se anula porque esta base mínima no tiene el esquema de la
    aplicación; el esquema real se valida en otros tests.
    """
    monkeypatch.setattr(backup_module, "model_tables", lambda: None)
    origen = tmp_path / "origen.db"
    crear_sqlite(origen, ["primera", "segunda"])
    carpeta = tmp_path / "backups"
    settings = BackupSettings(f"sqlite:///{origen.as_posix()}", carpeta, keep=10)
    return origen, carpeta, settings


@pytest.fixture
def app_archivo(tmp_path):
    """App con el esquema real de la aplicación en un archivo SQLite.

    Levanta las migraciones (igual que ``flask db upgrade``) y siembra datos, de
    modo que el respaldo cubra el esquema y los datos completos.
    """
    db_path = (tmp_path / "ddn.db").as_posix()

    class _BackupConfig(BackupConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    application = create_app(_BackupConfig)
    ctx = application.app_context()
    ctx.push()
    try:
        upgrade()
        seed_module.seed_database(reset=True)
        yield application
    finally:
        from app.extensions import db

        db.session.remove()
        db.engine.dispose()
        ctx.pop()


# ----------------------------------------------------------------------
# Camino SQLite: respaldo
# ----------------------------------------------------------------------
def test_respaldo_sqlite_es_una_copia_funcional(bd_simple):
    """El archivo generado se abre por separado y tiene los mismos datos."""
    origen, carpeta, settings = bd_simple

    destino = create_backup(settings)

    assert destino.parent == carpeta
    assert destino.name.startswith("ddn-") and destino.suffix == ".db"
    assert destino.stat().st_size > 0

    copia = sqlite3.connect(destino)
    try:
        assert copia.execute("select texto from notas order by id").fetchall() == [
            ("primera",),
            ("segunda",),
        ]
        assert copia.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        copia.close()

    # La base original no se toca.
    assert origen.read_bytes()
    assert sqlite3.connect(origen).execute(
        "select count(*) from notas").fetchone()[0] == 2


def test_respaldo_verifica_integridad_antes_de_devolverlo(bd_simple, monkeypatch):
    """Si el archivo resultante no es una base válida, el respaldo falla."""
    _origen, _carpeta, settings = bd_simple
    llamadas = []

    def _falso(origen, destino):
        Path(destino).write_bytes(b"no soy una base de datos")
        llamadas.append(destino)

    monkeypatch.setattr(backup_module, "_copy_sqlite", _falso)

    with pytest.raises(BackupError):
        create_backup(settings)
    assert llamadas, "la copia se intentó hacer"


def test_respaldo_exige_que_la_base_exista(tmp_path):
    """Sin archivo de base de datos el error es explícito."""
    settings = BackupSettings(
        f"sqlite:///{(tmp_path / 'no-existe.db').as_posix()}", tmp_path / "b", 10)

    with pytest.raises(BackupError, match="db upgrade"):
        create_backup(settings)


def test_no_se_respalda_una_base_en_memoria(tmp_path):
    settings = BackupSettings("sqlite:///:memory:", tmp_path / "b", 10)

    with pytest.raises(BackupError, match="memoria"):
        create_backup(settings)


def test_motor_no_soportado(tmp_path):
    settings = BackupSettings("mysql://localhost/ddn", tmp_path / "b", 10)

    with pytest.raises(BackupError, match="no soportado"):
        create_backup(settings)


# ----------------------------------------------------------------------
# Camino SQLite: restauración
# ----------------------------------------------------------------------
def test_restore_recupera_los_datos_originales(bd_simple):
    """Tras perder la base, ``restore_backup`` deja los datos del respaldo."""
    origen, _carpeta, settings = bd_simple

    respaldo = create_backup(settings)
    # Se destruye la base viva: se borra y se recrea con otro contenido.
    origen.unlink()
    crear_sqlite(origen, ["dato posterior"])

    copia_previa = restore_backup(respaldo, settings=settings)

    con = sqlite3.connect(origen)
    try:
        assert con.execute("select texto from notas order by id").fetchall() == [
            ("primera",),
            ("segunda",),
        ]
    finally:
        con.close()
    assert copia_previa is not None and copia_previa.exists()
    assert copia_previa.name.startswith("pre-restore-")


def test_restore_rechaza_un_archivo_que_no_es_sqlite(bd_simple):
    """Un archivo corrupto no se copia sobre la base viva."""
    origen, carpeta, settings = bd_simple
    antes = origen.read_bytes()

    carpeta.mkdir(parents=True, exist_ok=True)
    falso = carpeta / "ddn-20260101-000000.db"
    falso.write_text("esto no es una base de datos", encoding="utf-8")

    with pytest.raises(BackupError):
        restore_backup(falso, settings=settings)

    assert origen.read_bytes() == antes, "la base no debe tocarse"


def test_restore_rechaza_un_respaldo_de_otro_esquema(tmp_path):
    """Un SQLite válido pero sin las tablas esperadas no se restaura."""
    origen = tmp_path / "origen.db"
    crear_sqlite(origen, ["primera"])
    settings = BackupSettings(f"sqlite:///{origen.as_posix()}", tmp_path / "b", 10)

    respaldo = create_backup(settings)

    with pytest.raises(BackupError, match="tablas esperadas"):
        backup_module.verify_sqlite(respaldo, expected_tables=["users", "bookings"])


def test_verify_sqlite_detecta_archivo_inexistente(tmp_path):
    with pytest.raises(BackupError, match="No existe"):
        verify_sqlite(tmp_path / "no-existe.db")


# ----------------------------------------------------------------------
# Conservación de respaldos
# ----------------------------------------------------------------------
def test_conserva_solo_los_mas_recientes(tmp_path):
    carpeta = tmp_path / "backups"
    carpeta.mkdir()
    for marca in ("20260101-000000", "20260102-000000", "20260103-000000",
                  "20260104-000000", "20260105-000000"):
        (carpeta / f"ddn-{marca}.db").write_text("x", encoding="utf-8")

    borrados = prune_backups(carpeta, keep=3)

    assert len(borrados) == 2
    restantes = list_backups(carpeta)
    assert [p.name for p in restantes] == [
        "ddn-20260105-000000.db",
        "ddn-20260104-000000.db",
        "ddn-20260103-000000.db",
    ]


def test_prune_no_borra_los_archivos_protegidos(tmp_path):
    carpeta = tmp_path / "backups"
    viejo = carpeta / "ddn-20260101-000000.db"
    nuevo = carpeta / "ddn-20260102-000000.db"
    for p in (viejo, nuevo):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")

    prune_backups(carpeta, keep=1, protect={viejo})

    assert viejo.exists(), "el archivo protegido debe sobrevivir"
    assert nuevo.exists()


def test_list_backups_de_carpeta_inexistente(tmp_path):
    assert list_backups(tmp_path / "no-existe") == []


def test_keep_negativo_es_error(tmp_path):
    with pytest.raises(BackupError):
        prune_backups(tmp_path, keep=-1)


# ----------------------------------------------------------------------
# Comandos de consola
# ----------------------------------------------------------------------
def test_comando_flask_backup_crea_el_respaldo(app_archivo, tmp_path):
    carpeta = tmp_path / "backups"
    runner = app_archivo.test_cli_runner()

    resultado = runner.invoke(args=["backup", "--dir", str(carpeta)])

    assert resultado.exit_code == 0, resultado.output
    respaldos = list_backups(carpeta)
    assert len(respaldos) == 1
    assert respaldos[0].stat().st_size > 0
    assert "Respaldo creado" in resultado.output


def test_comando_flask_backup_restore(app_archivo, tmp_path):
    """Respaldo y restauración reales generados por el propio comando."""
    from app.extensions import db

    ruta = sqlite_file_from_uri(app_archivo.config["SQLALCHEMY_DATABASE_URI"])
    carpeta = tmp_path / "backups"
    runner = app_archivo.test_cli_runner()

    respaldo = create_backup(
        BackupSettings(app_archivo.config["SQLALCHEMY_DATABASE_URI"], carpeta, 10))

    # Se altera la base fuera de la app para comprobar que el restore la arregla.
    db.session.remove()
    con = sqlite3.connect(ruta)
    try:
        clientes_antes = con.execute("select count(*) from clients").fetchone()[0]
        con.execute("delete from clients")
        con.commit()
        assert con.execute("select count(*) from clients").fetchone()[0] == 0
    finally:
        con.close()

    resultado = runner.invoke(args=["backup", "--dir", str(carpeta), "--restore", str(respaldo)])

    assert resultado.exit_code == 0, resultado.output
    assert "restaurada" in resultado.output
    con = sqlite3.connect(ruta)
    try:
        assert con.execute("select count(*) from clients").fetchone()[0] == clientes_antes
    finally:
        con.close()


def test_script_backup_fuera_de_flask(tmp_path, monkeypatch, capsys):
    """``scripts/backup.py`` funciona sin contexto de Flask."""
    import importlib.util

    origen = tmp_path / "origen.db"
    crear_sqlite(origen, ["primera", "segunda"])
    carpeta = tmp_path / "backups"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{origen.as_posix()}")
    monkeypatch.setenv("BACKUP_DIR", str(carpeta))

    spec = importlib.util.spec_from_file_location(
        "ddn_backup_script", RAIZ / "scripts" / "backup.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    assert modulo.main([]) == 0
    assert len(list_backups(carpeta)) == 1
    assert "Respaldo creado" in capsys.readouterr().out

    assert modulo.main(["--list"]) == 0
    assert list_backups(carpeta)[0].name in capsys.readouterr().out

    # Un archivo inválido produce código de salida 1 y mensaje en stderr.
    malo = carpeta / "roto.db"
    malo.write_text("nada que ver aqui", encoding="utf-8")
    assert modulo.main(["--restore", str(malo)]) == 1
    assert "ERROR" in capsys.readouterr().err


# ----------------------------------------------------------------------
# Configuración de los respaldos
# ----------------------------------------------------------------------
def test_resolve_settings_desde_la_app(app_archivo):
    settings = resolve_settings(app_archivo)

    assert settings.database_uri == app_archivo.config["SQLALCHEMY_DATABASE_URI"]
    assert settings.backend == "sqlite"


def test_resolve_settings_fuera_de_flask_usa_el_entorno(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "respaldos"))
    monkeypatch.setenv("BACKUP_KEEP", "7")

    settings = resolve_settings()

    assert settings.backup_dir == tmp_path / "respaldos"
    assert settings.keep == 7


def test_resolve_settings_respeta_los_argumentos(app_archivo, tmp_path):
    settings = resolve_settings(app_archivo, backup_dir=tmp_path / "otro", keep=3)

    assert settings.backup_dir == tmp_path / "otro"
    assert settings.keep == 3


def test_backups_esta_ignorado_por_git():
    """La carpeta de respaldos nunca debe aparecer en el control de versiones."""
    gitignore = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert any(line.strip() == "backups/" for line in gitignore)


# ----------------------------------------------------------------------
# Camino PostgreSQL (escrito, pendiente de P9)
# ----------------------------------------------------------------------
def test_argumentos_de_pg_dump_y_pg_restore():
    """Construcción de la línea de comandos, sin tocar ningún servidor."""
    url = backup_module.make_url(
        "postgresql://usuario:secreto@localhost:6543/ddn_produccion")

    assert backup_module._pg_dump_args(url, Path("respaldo.dump")) == [
        "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
        "--host", "localhost", "--port", "6543",
        "--username", "usuario", "--dbname", "ddn_produccion",
        "--file", "respaldo.dump",
    ]
    assert backup_module._pg_restore_args(url, Path("respaldo.dump"))[:2] == [
        "pg_restore", "--clean",
    ]
    assert backup_module._pg_env(url)["PGPASSWORD"] == "secreto"


def test_firma_de_pg_dump_se_verifica(tmp_path):
    """Un respaldo de PostgreSQL debe empezar por la firma PGDMP."""
    bueno = tmp_path / "bueno.dump"
    bueno.write_bytes(b"PGDMP\x01" + b"\x00" * 32)
    malo = tmp_path / "malo.dump"
    malo.write_bytes(b"no soy un dump")

    settings = BackupSettings("postgresql://localhost/ddn", tmp_path, 10)

    backup_module.verify_sqlite_or_pg_dump(bueno, settings)
    with pytest.raises(BackupError, match="PGDMP"):
        backup_module.verify_sqlite_or_pg_dump(malo, settings)


@pytest.mark.skipif(shutil.which("pg_dump") is not None,
                    reason="pg_dump está instalado: el camino PostgreSQL "
                           "necesita una base real (pendiente de P9)")
def test_pg_dump_ausente_falla_con_mensaje_claro(tmp_path):
    """Sin PostgreSQL en este entorno, el error debe explicar qué falta.

    Este test NO valida el respaldo en PostgreSQL (imposible aquí): solo que la
    ausencia de la utilidad se reporta con un mensaje accionable. La
    verificación real queda para P9, cuando se configure el driver.
    """
    settings = BackupSettings("postgresql://localhost/ddn", tmp_path, 10)

    with pytest.raises(BackupError, match="pg_dump"):
        create_backup(settings)