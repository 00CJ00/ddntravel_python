"""Búsqueda avanzada (RF-16)."""
from __future__ import annotations

from sqlalchemy import or_, func
from sqlalchemy.orm import aliased

from .. import models as m
from ..extensions import db


def _escape_like(term: str) -> str:
    """Escapa caracteres especiales de LIKE para evitar inyección."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _paginate(query, page: int, per_page: int):
    """Aplica paginación y devuelve (items, total, pages)."""
    total = query.order_by(None).count()
    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    items = query.order_by(None).offset((page - 1) * per_page).limit(per_page).all()
    return items, total, pages


def search_packages(q, category="", destination="", min_price=None, max_price=None, min_stars=None, **kw):
    query = m.Package.query.filter(m.Package.deleted_at.is_(None))
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            m.Package.title.like(like, escape="\\"),
            m.Package.description.like(like, escape="\\"),
        ))
    if category:
        query = query.filter(m.Package.category == category)
    if destination:
        query = query.filter(m.Package.destination_name == destination)
    if min_price is not None:
        query = query.filter(m.Package.price_usd >= min_price)
    if max_price is not None:
        query = query.filter(m.Package.price_usd <= max_price)
    return query


def search_destinations(q, category="", destination="", **kw):
    query = m.Destination.query
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            m.Destination.name.like(like, escape="\\"),
            m.Destination.country.like(like, escape="\\"),
        ))
    return query


def search_hotels(q, category="", destination="", min_price=None, max_price=None, min_stars=None):
    query = m.Hotel.query.filter(m.Hotel.deleted_at.is_(None))
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(m.Hotel.name.like(like, escape="\\"))
    if destination:
        query = query.filter(m.Hotel.destination_name == destination)
    if min_stars is not None:
        query = query.filter(m.Hotel.stars >= min_stars)
    return query


def search_flights(q, category="", destination="", min_price=None, max_price=None):
    query = m.Flight.query.filter(m.Flight.deleted_at.is_(None))
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            m.Flight.airline.like(like, escape="\\"),
            m.Flight.origin.like(like, escape="\\"),
            m.Flight.destination.like(like, escape="\\"),
        ))
    if destination:
        query = query.filter(m.Flight.destination == destination)
    return query


def search_activities(q, category="", destination="", **kw):
    query = m.Activity.query
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            m.Activity.title.like(like, escape="\\"),
            m.Activity.description.like(like, escape="\\"),
        ))
    if destination:
        query = query.filter(m.Activity.destination_name == destination)
    return query


def search_transports(q, category="", destination="", **kw):
    query = m.Transport.query
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            m.Transport.type.like(like, escape="\\"),
            m.Transport.route.like(like, escape="\\"),
            m.Transport.vehicle_model.like(like, escape="\\"),
        ))
    return query


def search_bookings(q, category="", destination="", status="",
                    current_user=None, is_staff=False):
    query = m.Booking.query
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            m.Booking.booking_code.like(like, escape="\\"),
            m.Booking.destination_name.like(like, escape="\\"),
        ))
    if status:
        query = query.filter(m.Booking.status == status)
    if destination:
        query = query.filter(m.Booking.destination_name == destination)
    if not is_staff and current_user is not None:
        from ..repositories import people
        client = people.get_client_by_email(current_user.email)
        if client is None:
            return m.Booking.query.filter(m.Booking.id == -1)
        query = query.filter(m.Booking.client_id == client.id)
    return query


def search_clients(q, category="", destination="", **kw):
    query = m.Client.query
    if q:
        like = f"%{_escape_like(q)}%"
        query = query.filter(or_(
            m.Client.name.like(like, escape="\\"),
            m.Client.email.like(like, escape="\\"),
            m.Client.document_id.like(like, escape="\\"),
        ))
    return query


SEARCHERS = {
    "packages": search_packages,
    "destinations": search_destinations,
    "hotels": search_hotels,
    "flights": search_flights,
    "activities": search_activities,
    "transports": search_transports,
    "bookings": search_bookings,
    "clients": search_clients,
}
