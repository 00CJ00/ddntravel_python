"""Itinerarios de viaje (RF-10)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow

SOURCES = ("ia", "manual")


class Itinerary(BaseEntity, db.Model):
    """Itinerario generado por IA o creado manualmente."""

    __tablename__ = "itineraries"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), index=True)
    destination = db.Column(db.String(160))
    days = db.Column(db.Integer, default=0)
    source = db.Column(db.String(10), default="manual")
    content = db.Column(db.JSON, default=dict)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
