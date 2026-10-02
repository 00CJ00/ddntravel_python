"""Usuarios y roles del sistema (RF-01, RF-02)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow

ROLES = ("admin", "employee", "client")


class User(BaseEntity, db.Model):
    """Usuario (administrador, empleado o cliente)."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255))
    role = db.Column(db.String(20), nullable=False, default="client")
    department = db.Column(db.String(120))
    avatar = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    google_id = db.Column(db.String(120), unique=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    client = db.relationship("Client", foreign_keys=[client_id])

    def describe(self) -> str:
        return f"{self.name} ({self.role})"
