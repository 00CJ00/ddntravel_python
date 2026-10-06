"""Vuelos (RF-08, RN-01)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Flight(BaseEntity, db.Model):
    """Vuelo ofertado por la agencia."""

    __tablename__ = "flights"

    id = db.Column(db.Integer, primary_key=True)
    airline = db.Column(db.String(120), index=True)
    flight_number = db.Column(db.String(30), index=True)
    origin = db.Column(db.String(120))
    destination = db.Column(db.String(120))
    departure_time = db.Column(db.String(40))
    arrival_time = db.Column(db.String(40))
    price_usd = db.Column(db.Numeric(12, 2), default=0)
    seats_available = db.Column(db.Integer, default=0)
    total_seats = db.Column(db.Integer, default=0)
    flight_class = db.Column(db.String(40))
    status = db.Column(db.String(20), default="Disponible", index=True)
    baggage_allowance = db.Column(db.String(80))
    image = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def describe(self) -> str:
        return f"{self.airline} {self.flight_number}"
