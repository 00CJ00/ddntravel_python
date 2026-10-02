"""Paquetes turísticos (RF-05, RN-01)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Package(BaseEntity, db.Model):
    """Paquete turístico. Controla su disponibilidad (RN-01)."""

    __tablename__ = "packages"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    destination_id = db.Column(db.Integer, db.ForeignKey("destinations.id"))
    destination_name = db.Column(db.String(160), index=True)
    duration_days = db.Column(db.Integer, default=0)
    duration_nights = db.Column(db.Integer, default=0)
    price_usd = db.Column(db.Numeric(12, 2), default=0)
    original_price_usd = db.Column(db.Numeric(12, 2), default=0)
    available_slots = db.Column(db.Integer, default=0)
    total_slots = db.Column(db.Integer, default=0)
    max_capacity = db.Column(db.Integer, default=0)
    image = db.Column(db.String(500))
    image_url = db.Column(db.String(500))
    gallery = db.Column(db.JSON, default=list)
    category = db.Column(db.String(60), index=True)
    featured = db.Column(db.Boolean, default=False)
    inclusions = db.Column(db.JSON, default=list)
    itinerary_summary = db.Column(db.Text)
    description = db.Column(db.Text)
    departure_dates = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    destination = db.relationship("Destination")

    def has_availability(self, travelers: int) -> bool:
        return (self.available_slots or 0) >= travelers

    def reserve_slots(self, travelers: int) -> None:
        self.available_slots = max(0, (self.available_slots or 0) - travelers)

    def release_slots(self, travelers: int) -> None:
        max_slots = self.total_slots or self.max_capacity or ((self.available_slots or 0) + travelers)
        self.available_slots = min(max_slots, (self.available_slots or 0) + travelers)

    def describe(self) -> str:
        return f"{self.title} — {self.destination_name}"
