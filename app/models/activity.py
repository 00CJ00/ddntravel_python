"""Actividades turísticas (RF-18)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Activity(BaseEntity, db.Model):
    """Actividad turística ofertada por la agencia."""

    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    destination_id = db.Column(db.Integer, db.ForeignKey("destinations.id"))
    destination_name = db.Column(db.String(160), index=True)
    duration_hours = db.Column(db.Integer, default=0)
    price_usd = db.Column(db.Numeric(12, 2), default=0)
    includes_guide = db.Column(db.Boolean, default=False)
    difficulty = db.Column(db.String(40))
    image = db.Column(db.String(500))
    description = db.Column(db.Text)
    category = db.Column(db.String(60), index=True)
    schedule = db.Column(db.String(120))
    includes = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def describe(self) -> str:
        return self.title
