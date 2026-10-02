"""Clientes registrados en el CRM (RF-03)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Client(BaseEntity, db.Model):
    """Cliente de la agencia."""

    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), unique=True, index=True)
    phone = db.Column(db.String(40))
    document_id = db.Column(db.String(60))
    category = db.Column(db.String(40))
    budget_preference = db.Column(db.String(80))
    preferred_destinations = db.Column(db.JSON, default=list)
    trips_count = db.Column(db.Integer, default=0)
    total_spent = db.Column(db.Numeric(12, 2), default=0)
    registration_date = db.Column(db.Date)
    status = db.Column(db.String(20), default="Activo", index=True)
    notes = db.Column(db.Text)
    passport_expiry = db.Column(db.Date)
    nationality = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True))

    def register_trip(self, amount) -> None:
        """Actualiza las estadísticas del cliente tras registrar una reserva."""
        self.trips_count = (self.trips_count or 0) + 1
        self.total_spent = (self.total_spent or 0) + amount

    def describe(self) -> str:
        return f"{self.name} ({self.category})"
