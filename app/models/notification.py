"""Notificaciones y su lectura por usuario (RF-13)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Notification(BaseEntity, db.Model):
    """Aviso mostrado en la campana de la interfaz."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    message = db.Column(db.Text)
    type = db.Column(db.String(20), default="info")
    # Texto de fecha ("Justo ahora", "Hace 2 horas") que usa la plantilla.
    date = db.Column(db.String(40))
    read = db.Column(db.Boolean, default=False)
    link_tab = db.Column(db.String(40))
    visible_roles = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    reads = db.relationship(
        "NotificationRead", back_populates="notification", cascade="all, delete-orphan")


class NotificationRead(BaseEntity, db.Model):
    """Marca de lectura de una notificación para un usuario concreto."""

    __tablename__ = "notification_reads"

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(
        db.Integer, db.ForeignKey("notifications.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    read_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    notification = db.relationship("Notification", back_populates="reads")

    __table_args__ = (
        db.UniqueConstraint("notification_id", "user_id", name="uq_notification_user"),
    )
