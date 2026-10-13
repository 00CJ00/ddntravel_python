"""Alertas automáticas de DDN Travel (fase P6).

Detecta pasaportes próximos a vencer, saldos pendientes con salida cercana,
paquetes con pocos cupos y reservas estancadas sin pago. Cada alerta tiene
una identidad estable ``alerta:tipo:entidad:id:fecha`` que se guarda en
``Notification.event_key`` (UNIQUE): repetir la ejecución (o dos procesos a
la vez) no duplica. Solo confirma por alerta; un duplicado en carrera hace
rollback de esa alerta sin abortar el lote.
"""
from __future__ import annotations

import datetime
import logging

log = logging.getLogger(__name__)

KIND_PASSPORT = "passport_expiry"
KIND_BALANCE = "pending_balance"
KIND_AVAILABILITY = "low_availability"
KIND_STALE = "stale_pending"


def _today() -> datetime.date:
    return datetime.date.today()


def _as_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_naive_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value


def _departure_of(booking):
    return _as_date(getattr(booking, "departure_date", None)
                    or getattr(booking, "check_in", None))


def _active_bookings(store):
    return [b for b in store.bookings if getattr(b, "status", None) != "Cancelada"]


def _has_valid_payment(store, booking) -> bool:
    """Algún pago `Completado` de kind pago (no reembolsos ni anulados)."""
    return any(p.booking_id == booking.id and p.status == "Completado"
               and p.kind != "reembolso" for p in store.payments)


def detect_passport_expiry(store, today=None) -> list:
    """Pasaporte que vence antes de que pasen 6 meses desde la salida."""
    from .documents import add_months
    today = today or _today()
    found = []
    for booking in _active_bookings(store):
        departure = _departure_of(booking)
        if departure is None or departure < today:
            continue
        client = next((c for c in store.clients if c.id == booking.client_id), None)
        expiry = _as_date(getattr(client, "passport_expiry", None)) if client else None
        if expiry is None or expiry >= add_months(departure, 6):
            continue
        found.append({
            "kind": KIND_PASSPORT, "entity_type": "Booking",
            "entity_id": booking.id,
            "title": "Pasaporte por vencer",
            "message": (f"El pasaporte del cliente {booking.client_name} vence el "
                        f"{expiry.isoformat()}, con salida el {departure.isoformat()} "
                        f"(reserva {booking.booking_code})."),
            "link_tab": "clients",
        })
    return found


def detect_pending_balance(store, today=None) -> list:
    """Saldo pendiente con salida en ≤ 15 días (hoy incluido)."""
    today = today or _today()
    limit = today + datetime.timedelta(days=15)
    found = []
    for booking in _active_bookings(store):
        departure = _departure_of(booking)
        if departure is None or not (today <= departure <= limit):
            continue
        balance = float(getattr(booking, "total_price", 0) or 0) \
            - float(getattr(booking, "amount_paid", 0) or 0)
        if balance <= 0:
            continue
        found.append({
            "kind": KIND_BALANCE, "entity_type": "Booking",
            "entity_id": booking.id,
            "title": "Saldo pendiente con salida próxima",
            "message": (f"La reserva {booking.booking_code} sale el "
                        f"{departure.isoformat()} con saldo pendiente de "
                        f"${balance:,.2f} USD."),
            "link_tab": "bookings",
        })
    return found


def detect_low_availability(store) -> list:
    """Paquetes con cupos disponibles ≤ 20 % del total real."""
    found = []
    for package in store.packages:
        total = int(getattr(package, "total_slots", 0) or 0) \
            or int(getattr(package, "max_capacity", 0) or 0)
        if total <= 0:
            continue
        available = int(getattr(package, "available_slots", 0) or 0)
        if available / total > 0.2:
            continue
        found.append({
            "kind": KIND_AVAILABILITY, "entity_type": "Package",
            "entity_id": package.id,
            "title": "Paquete con pocos cupos",
            "message": (f"El paquete {package.title} solo tiene {available} de "
                        f"{total} cupos disponibles (≤ 20 %)."),
            "link_tab": "dashboard",
        })
    return found


def detect_stale_pending(store, now=None) -> list:
    """Reservas `Pendiente` sin pago válido por más de 72 horas."""
    now = _as_naive_utc(now) or datetime.datetime.now()
    cutoff = now - datetime.timedelta(hours=72)
    found = []
    for booking in store.bookings:
        if getattr(booking, "status", None) != "Pendiente":
            continue
        created = _as_naive_utc(getattr(booking, "created_at", None))
        if created is None or created >= cutoff:
            continue
        if _has_valid_payment(store, booking):
            continue
        found.append({
            "kind": KIND_STALE, "entity_type": "Booking",
            "entity_id": booking.id,
            "title": "Reserva pendiente sin pago",
            "message": (f"La reserva {booking.booking_code} lleva más de 72 h "
                        f"en Pendiente sin ningún pago válido."),
            "link_tab": "bookings",
        })
    return found


def detect_all(store, today=None, now=None) -> list:
    """Las cuatro detecciones juntas (sin efectos secundarios)."""
    return (detect_passport_expiry(store, today)
            + detect_pending_balance(store, today)
            + detect_low_availability(store)
            + detect_stale_pending(store, now))


def alert_key(alert, day=None) -> str:
    """Identidad estable entidad + tipo + fecha (clave UNIQUE)."""
    day = day or _today().isoformat()
    return f"alert:{alert['kind']}:{alert['entity_type']}:{alert['entity_id']}:{day}"


def run_alerts(store, user=None, today=None, now=None) -> dict:
    """Genera las notificaciones de alerta (idempotente) y audita la corrida.

    Cada alerta confirma por separado: si otra ejecución la creó primero, se
    revierte solo esa y el lote continúa. Devuelve conteos.
    """
    from sqlalchemy.exc import IntegrityError

    created, skipped = 0, 0
    day = today.isoformat() if isinstance(today, datetime.date) else None
    for alert in detect_all(store, today, now):
        key = alert_key(alert, day)
        try:
            if store.add_notification(
                    alert["title"], alert["message"], "warning",
                    alert["link_tab"], event_key=key):
                created += 1
            else:
                skipped += 1
        except IntegrityError:
            # Otra ejecución concurrente la registró primero.
            store._rollback()
            skipped += 1
        except Exception as exc:  # noqa: BLE001 - una alerta no tumba el lote
            store._rollback()
            log.warning("Alerta omitida (%s): %s", key, exc)
            skipped += 1
    store.log_action(getattr(user, "id", None) if user else "system",
                     getattr(user, "name", None) if user else "Sistema",
                     "ALERTAS_GENERADAS", "Alertas",
                     f"Alertas automáticas: {created} creadas, {skipped} omitidas.")
    return {"created": created, "skipped": skipped,
            "total": created + skipped}
