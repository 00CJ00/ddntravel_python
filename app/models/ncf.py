"""Secuencias de NCF (comprobantes fiscales) — RF-11, fase P4."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class NcfSequence(BaseEntity, db.Model):
    """Contador persistente de comprobantes fiscales por prefijo."""

    __tablename__ = "ncf_sequences"

    prefix = db.Column(db.String(8), primary_key=True)
    current = db.Column(db.Integer, nullable=False, default=0)
    max_number = db.Column(db.Integer, nullable=False, default=0)
    expires_on = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def describe(self) -> str:
        return f"{self.prefix}: {self.current}/{self.max_number}"
