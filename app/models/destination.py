"""Destinos turísticos (RF-04)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Destination(BaseEntity, db.Model):
    """Destino turístico ofertado por la agencia."""

    __tablename__ = "destinations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    country = db.Column(db.String(80))
    region = db.Column(db.String(80))
    cover_image = db.Column(db.String(500))
    description = db.Column(db.Text)
    weather_type = db.Column(db.String(60))
    best_season = db.Column(db.String(60))
    high_season_months = db.Column(db.JSON, default=list)
    popular_attractions = db.Column(db.JSON, default=list)
    base_price_usd = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(20), default="Activo", index=True)
    rating = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def describe(self) -> str:
        return f"{self.name}, {self.country}"
