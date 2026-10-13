"""Programación de las alertas automáticas (fase P6).

El scheduler solo arranca cuando ``ENABLE_SCHEDULER=1`` y nunca en tests ni
en el proceso padre del reloader. ``flask alerts run`` funciona sin él.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_SCHEDULER_KEY = "ddn_alert_scheduler"


def start_scheduler_if_enabled(app) -> bool:
    """Arranca el job diario de alertas si corresponde. Devuelve si arrancó."""
    if not app.config.get("ENABLE_SCHEDULER"):
        return False
    if app.config.get("TESTING"):
        return False
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        # Proceso padre del reloader: el hijo lo arrancará.
        return False
    if app.extensions.get(_SCHEDULER_KEY) is not None:
        return True  # ya hay una instancia en este proceso
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        log.warning("APScheduler no instalado: las alertas solo corren con 'flask alerts run'.")
        return False
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_alerts_job, "interval",
        hours=int(app.config.get("ALERTS_INTERVAL_HOURS", 24)),
        args=[app], id="alertas-diarias", replace_existing=True,
        misfire_grace_time=3600, coalesce=True, max_instances=1,
    )
    scheduler.start()
    app.extensions[_SCHEDULER_KEY] = scheduler
    log.info("Scheduler de alertas iniciado (cada %s h).",
             app.config.get("ALERTS_INTERVAL_HOURS", 24))
    return True


def _run_alerts_job(app) -> None:
    """Job diario: ejecuta las alertas con contexto propio; no propaga fallos."""
    try:
        with app.app_context():
            from . import alerts as alerts_module
            from .store import store
            counts = alerts_module.run_alerts(store)
            log.info("Alertas programadas: %s", counts)
    except Exception as exc:  # noqa: BLE001 - el job registra y sigue
        log.warning("Falló el job de alertas programadas: %s", exc)
