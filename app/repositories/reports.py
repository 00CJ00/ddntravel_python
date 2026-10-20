"""Reportes en PDF y XLSX (RF-15)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func

from .. import models as m
from ..extensions import db

MAX_ROWS = 10_000


def bookings_report(date_from=None, date_to=None, status="", destination=""):
    query = m.Booking.query
    if date_from:
        query = query.filter(m.Booking.created_at >= date_from)
    if date_to:
        query = query.filter(m.Booking.created_at <= date_to)
    if status:
        query = query.filter(m.Booking.status == status)
    if destination:
        query = query.filter(m.Booking.destination_name == destination)
    return query.limit(MAX_ROWS).all()


def clients_report(date_from=None, date_to=None, status="", destination=""):
    query = m.Client.query.filter(m.Client.deleted_at.is_(None))
    if date_from:
        query = query.filter(m.Client.created_at >= date_from)
    if date_to:
        query = query.filter(m.Client.created_at <= date_to)
    return query.limit(MAX_ROWS).all()


def occupancy_report(date_from=None, date_to=None, status="", destination=""):
    hotels = m.Hotel.query.filter(m.Hotel.deleted_at.is_(None)).all()
    bookings = m.Booking.query.filter(m.Booking.status != "Cancelada").all()
    rows = []
    for hotel in hotels:
        total_rooms = sum(rt.rooms_total or 0 for rt in (hotel.room_types or []))
        occupied = sum(
            (b.rooms_count or 1) for b in bookings
            if b.hotel_id == hotel.id
        )
        pct = round((occupied / total_rooms) * 100, 1) if total_rooms else 0
        rows.append({
            "hotel": hotel.name,
            "destination": hotel.destination_name,
            "total_rooms": total_rooms,
            "occupied": occupied,
            "pct": pct,
        })
    return rows


REPORTS = {
    "bookings": bookings_report,
    "clients": clients_report,
    "occupancy": occupancy_report,
}
