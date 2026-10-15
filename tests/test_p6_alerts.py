"""Tests deterministas de alertas automáticas (RF-13) — Fase P6."""
from datetime import date, datetime, timedelta, timezone

from conftest import ADMIN_EMAIL, CLIENT_EMAIL

from app import models as m
from app.extensions import db


def _create_old_pending_booking(store, today, now):
    admin = m.User.query.filter_by(email=ADMIN_EMAIL).one()
    client = m.Client.query.filter_by(email=CLIENT_EMAIL).one()
    result = store.create_booking(
        admin,
        client_id=client.id,
        client_name=client.name,
        client_email=client.email,
        destination_name="Punta Cana",
        departure_date=today + timedelta(days=10),
        return_date=today + timedelta(days=15),
        travelers=1,
        total_price=1000,
    )
    assert result["success"]
    booking = result["booking"]
    booking.created_at = now - timedelta(days=4)
    client.passport_expiry = today + timedelta(days=90)
    package = m.Package.query.first()
    package.available_slots = 4
    package.total_slots = 20
    db.session.commit()
    return booking, package


def test_alertas_crean_las_cuatro_reglas_sin_duplicar(store):
    from app.alerts import run_alerts

    today = date(2026, 10, 13)
    now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    booking, package = _create_old_pending_booking(store, today, now)

    created = run_alerts(run_date=today, now=now)
    records = m.AlertRecord.query.filter_by(run_date=today).all()
    keys = {(record.alert_type, record.entity_type, record.entity_id) for record in records}
    expected = {
        ("passport_expiring", "booking", str(booking.id)),
        ("balance_due_before_departure", "booking", str(booking.id)),
        ("pending_booking_no_payment", "booking", str(booking.id)),
        ("package_low_availability", "package", str(package.id)),
    }

    assert expected <= keys
    assert created == len(records)
    assert run_alerts(run_date=today, now=now) == 0
    assert m.AlertRecord.query.filter_by(run_date=today).count() == len(records)
    assert m.Notification.query.count() >= len(records)


def test_comando_alerts_run_crea_alertas_sobre_reserva_de_seed(app):
    booking = m.Booking.query.filter_by(booking_code="DDN-2026-883").one()
    assert m.Payment.query.filter_by(booking_id=booking.id).count() == 0
    booking.created_at = datetime.now(timezone.utc) - timedelta(days=4)
    db.session.commit()

    cli_result = app.test_cli_runner().invoke(args=["alerts", "run"])

    assert cli_result.exit_code == 0, cli_result.output
    assert "Alertas creadas:" in cli_result.output
    assert m.AlertRecord.query.filter_by(
        entity_type="booking",
        entity_id=str(booking.id),
        alert_type="pending_booking_no_payment",
    ).count() == 1


def test_scheduler_permanece_apagado_por_defecto(app):
    assert app.config["ENABLE_SCHEDULER"] is False
    assert "ddn_travel_alert_scheduler" not in app.extensions
