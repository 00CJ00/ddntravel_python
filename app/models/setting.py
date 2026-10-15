"""Configuración persistente clave/valor (predictive_data y contadores)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Setting(BaseEntity, db.Model):
    """Par clave/valor con contenido JSON."""

    __tablename__ = "settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.JSON)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow,
                           onupdate=utcnow)
