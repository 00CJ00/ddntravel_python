"""Generación idempotente de alertas automáticas (RF-13)."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.exc import IntegrityError

from . import audit
from . import models as m
from .extensions import db
from .repositories import notifications as notifications_repo
from .repositories.base import to_decimal

STAFF_ROLES = ["admin", "employee"]


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _candidates(run_date: date, now: datetime):
    bookings = m.Booking.query.filter(
        m.Booking.deleted_at.is_(None),
        m.Booking.status.notin_(("Cancelada", "Completada")),
    ).all()
    packages = m.Package.query.filter(m.Package.deleted_at.is_(None)).all()
    paid_booking_ids = {
        booking_id
        for (booking_id,) in db.session.query(m.Payment.booking_id).filter(
            m.Payment.kind == "pago",
            m.Payment.status != "Anulado",
        ).all()
    }
    passport_expiries = {
        client.id: client.passport_expiry
        for client in m.Client.query.filter(m.Client.passport_expiry.isnot(None)).all()
    }
    for document in m.TravelDocument.query.filter(
        m.TravelDocument.expiry_date.isnot(None)
    ).all():
        if "pasaporte" in (document.doc_type or "").casefold():
            existing = passport_expiries.get(document.client_id)
            if existing is None or document.expiry_date < existing:
                passport_expiries[document.client_id] = document.expiry_date

    for booking in bookings:
        departure = booking.departure_date
        expiry = passport_expiries.get(booking.client_id)
        if (departure is not None and departure >= run_date and expiry is not None
                and expiry < _add_months(departure, 6)):
            yield (
                "passport_expiring",
                "booking",
                booking.id,
                "Pasaporte próximo a vencer",
                (
                    f"El pasaporte del cliente de la reserva {booking.booking_code} "
                    "vence antes de cumplir seis meses de vigencia desde la salida."
                ),
            )

        if departure is not None:
            days_until_departure = (departure - run_date).days
            balance = max(
                0,
                to_decimal(booking.total_price) - to_decimal(booking.amount_paid),
            )
            if 0 <= days_until_departure <= 15 and balance > 0:
                yield (
                    "balance_due_before_departure",
                    "booking",
                    booking.id,
                    "Saldo pendiente antes de la salida",
                    (
                        f"La reserva {booking.booking_code} sale en {days_until_departure} "
                        f"días y tiene un saldo pendiente de ${balance:.2f} USD."
                    ),
                )

        if (booking.status == "Pendiente"
                and to_decimal(booking.amount_paid) == 0
                and booking.id not in paid_booking_ids
                and booking.created_at is not None
                and _aware_utc(booking.created_at) < now - timedelta(hours=72)):
            yield (
                "pending_booking_no_payment",
                "booking",
                booking.id,
                "Reserva pendiente sin pago",
                (
                    f"La reserva {booking.booking_code} lleva más de 72 horas pendiente "
                    "y aún no tiene pagos registrados."
                ),
            )

    for package in packages:
        total_slots = int(package.total_slots or 0)
        available_slots = int(package.available_slots or 0)
        if total_slots > 0 and available_slots * 5 <= total_slots:
            yield (
                "package_low_availability",
                "package",
                package.id,
                "Paquete con pocos cupos",
                (
                    f"El paquete {package.title} tiene {available_slots} de "
                    f"{total_slots} cupos disponibles (20 % o menos)."
                ),
            )


def run_alerts(*, run_date: date | None = None, now: datetime | None = None) -> int:
    """Crea notificaciones por regla y devuelve cuántas se insertaron."""
    current_time = _aware_utc(now or datetime.now(timezone.utc))
    execution_date = run_date or current_time.date()
    created = 0
    try:
        for alert_type, entity_type, entity_id, title, message in _candidates(
            execution_date, current_time
        ):
            key = {
                "alert_type": alert_type,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "run_date": execution_date,
            }
            if m.AlertRecord.query.filter_by(**key).first() is not None:
                continue

            try:
                with db.session.begin_nested():
                    notification = notifications_repo.create_notification(
                        title,
                        message,
                        ntype="warning",
                        link_tab="bookings" if entity_type == "booking" else "catalog",
                        visible_roles=STAFF_ROLES,
                    )
                    record = m.AlertRecord(
                        **key,
                        notification_id=notification.id,
                    )
                    db.session.add(record)
                    db.session.flush()
                    audit.record(
                        "GENERAR_ALERTA",
                        "Notificaciones",
                        record,
                        details=f"Alerta {alert_type} para {entity_type} {entity_id}.",
                    )
                created += 1
            except IntegrityError:
                duplicate = m.AlertRecord.query.filter_by(**key).first()
                if duplicate is None:
                    raise

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return created


def start_scheduler(app):
    """Programa la evaluación diaria; el caller controla el interruptor."""
    scheduler = BackgroundScheduler(timezone="UTC")

    def run_in_app_context():
        with app.app_context():
            run_alerts()

    scheduler.add_job(
        run_in_app_context,
        trigger="cron",
        hour=2,
        minute=0,
        id="ddn-travel-daily-alerts",
        replace_existing=True,
    )
    scheduler.start()
    app.extensions["ddn_travel_alert_scheduler"] = scheduler
    return scheduler
