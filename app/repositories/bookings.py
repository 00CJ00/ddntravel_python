"""Repositorio de reservas: creación, inventario y cancelación (RN-01 a RN-03)."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from .. import models as m
from .base import all_of, get, save, to_decimal, to_int


def list_bookings():
    return all_of(m.Booking, m.Booking.id)


def get_booking(ident):
    return get(m.Booking, ident)


def create_booking_record(**data):
    """Inserta la reserva y genera el código ``DDN-{año}-{id:05d}`` a partir de la PK."""
    booking = m.Booking(booking_code=f"TMP-{uuid4().hex}")
    allowed = {
        "client_id", "package_id", "package_name", "destination_name", "hotel_id",
        "hotel_name", "room_type_id", "rooms_count", "check_in", "check_out",
        "flight_id", "flight_number", "transport_id", "departure_date", "return_date",
        "travelers", "total_price", "amount_paid", "status", "payment_status",
        "notes", "created_by",
    }
    from .base import assign_by_type
    assign_by_type(booking, data, allowed=allowed)
    save(booking)
    booking.booking_code = f"DDN-{date.today().year}-{booking.id:05d}"
    return booking


def add_passengers(booking, passengers) -> None:
    for p in passengers or []:
        save(m.BookingPassenger(
            booking_id=booking.id, full_name=p.get("full_name"),
            document=p.get("document"),
            age=to_int(p.get("age")) if p.get("age") not in (None, "") else None,
            phone=p.get("phone"),
        ))


def apply_payment(booking, amount) -> None:
    booking.apply_payment(to_decimal(amount))


def set_status(booking, status) -> None:
    booking.status = status


def cancel(booking, reason: str = "") -> None:
    booking.status = "Cancelada"
    suffix = f" [Cancelada: {reason or 'Por solicitud'}]"
    booking.notes = f"{booking.notes or ''}{suffix}"
