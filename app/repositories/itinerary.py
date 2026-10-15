"""Repositorio de itinerarios (RF-10)."""
from __future__ import annotations

from .. import models as m
from .base import all_of, get, save


def list_for_booking(booking_id):
    return [it for it in all_of(m.Itinerary, m.Itinerary.id) if it.booking_id == booking_id]


def get_itinerary(ident):
    return get(m.Itinerary, ident)


def create_itinerary(data):
    return save(m.Itinerary(**data))


def delete_itinerary(obj) -> None:
    from .base import delete
    delete(obj)
