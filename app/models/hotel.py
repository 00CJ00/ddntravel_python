"""Hoteles y tipos de habitación (RF-07, RN-01)."""
from __future__ import annotations

from sqlalchemy.orm import synonym

from ..extensions import db
from .base import BaseEntity, utcnow


class Hotel(BaseEntity, db.Model):
    """Hotel ofertado por la agencia."""

    __tablename__ = "hotels"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    destination_id = db.Column(db.Integer, db.ForeignKey("destinations.id"))
    destination_name = db.Column(db.String(160), index=True)
    stars = db.Column(db.Integer, default=0)
    address = db.Column(db.String(255))
    rating = db.Column(db.Float, default=0)
    image = db.Column(db.String(500))
    contact_phone = db.Column(db.String(40))
    amenities = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    room_types = db.relationship(
        "RoomType", back_populates="hotel", cascade="all, delete-orphan")

    def describe(self) -> str:
        return f"{self.name} ({self.stars}★)"


class RoomType(BaseEntity, db.Model):
    """Tipo de habitación de un hotel."""

    __tablename__ = "room_types"

    id = db.Column(db.Integer, primary_key=True)
    hotel_id = db.Column(db.Integer, db.ForeignKey("hotels.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    price_per_night = db.Column(db.Numeric(12, 2), default=0)
    rooms_total = db.Column(db.Integer, default=0)
    # Alias de compatibilidad: las plantillas usan ``room.type``.
    type = synonym("name")

    hotel = db.relationship("Hotel", back_populates="room_types")
