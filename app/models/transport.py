"""Transporte turístico (RF-09, RN-01)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Transport(BaseEntity, db.Model):
    """Unidad de transporte turístico."""

    __tablename__ = "transports"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(80))
    route = db.Column(db.String(160))
    vehicle_model = db.Column(db.String(120))
    capacity = db.Column(db.Integer, default=0)
    available_seats = db.Column(db.Integer, default=0)
    driver_name = db.Column(db.String(120))
    price_usd = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(20), default="Disponible", index=True)
    amenities = db.Column(db.JSON, default=list)
    image = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def describe(self) -> str:
        return f"{self.type} — {self.route}"
