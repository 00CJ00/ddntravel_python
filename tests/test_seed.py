"""Idempotencia del sembrado y comando ``flask seed`` (fase P2, paso 7)."""
from app import models as m
from app import seed as seed_module
from app.extensions import db


def _conteos() -> dict:
    """Número de filas por tabla (para comparar antes/después de sembrar)."""
    conteos = {}
    for name in m.__all__:
        obj = getattr(m, name)
        if isinstance(obj, type) and hasattr(obj, "__tablename__"):
            conteos[name] = db.session.query(obj).count()
    return conteos


def test_seed_es_idempotente(app):
    """Sembrar dos veces no duplica filas ni falla la segunda vez."""
    seed_module.clear_database()
    db.session.commit()

    assert seed_module.seed_database() is True
    primera = _conteos()

    assert seed_module.seed_database() is False
    segunda = _conteos()

    assert primera == segunda
    assert primera[m.User.__name__] > 0


def test_seed_reset_reinserta_sin_duplicar_auditoria(app):
    """``--reset`` limpia y reinserta; la auditoría no se duplica."""
    seed_module.seed_database(reset=True)
    primera = _conteos()
    seed_module.seed_database(reset=True)
    assert _conteos() == primera


def test_cli_seed_sin_reset_no_modifica_una_bd_ya_sembrada(app):
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["seed"])
    assert resultado.exit_code == 0
    assert "ya contiene datos" in resultado.output


def test_cli_seed_reset_permitido_en_desarrollo(app):
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["seed", "--reset"])
    assert resultado.exit_code == 0
    assert "cargados" in resultado.output


def test_cli_seed_reset_bloqueado_fuera_de_desarrollo(make_app):
    application = make_app(ENV="production")
    runner = application.test_cli_runner()
    resultado = runner.invoke(args=["seed", "--reset"])
    assert resultado.exit_code != 0
    assert "desarrollo" in resultado.output
