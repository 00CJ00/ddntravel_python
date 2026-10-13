"""Repositorio de itinerarios de viaje (RF-10, fase P6)."""
from __future__ import annotations

from .. import models as m
from .base import delete, get, save


def get_itinerary(ident):
    return get(m.Itinerary, ident)


def get_by_booking(booking_id):
    """Devuelve el itinerario vigente de una reserva o ``None``."""
    return (m.Itinerary.query
            .filter_by(booking_id=booking_id)
            .order_by(m.Itinerary.id.desc())
            .first())


def save_itinerary(booking, content: dict, source: str = "manual",
                   user=None) -> m.Itinerary:
    """Crea o actualiza (upsert) el itinerario de una reserva.

    Solo hace ``flush``: la confirmación la centraliza ``DataStore._commit``.
    """
    itinerary = get_by_booking(booking.id)
    if itinerary is None:
        itinerary = m.Itinerary(
            booking_id=booking.id, client_id=booking.client_id,
            destination=booking.destination_name,
            created_by=getattr(user, "id", None),
        )
        save(itinerary)
    itinerary.content = dict(content)
    itinerary.source = source if source in ("ia", "manual") else "manual"
    if getattr(itinerary, "days", None) in (None, 0):
        days = content.get("days")
        itinerary.days = len(days) if isinstance(days, list) else 0
    return itinerary


def delete_itinerary(obj) -> None:
    delete(obj)
