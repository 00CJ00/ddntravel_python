"""Registro idempotente de alertas automáticas (RF-13)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class AlertRecord(BaseEntity, db.Model):
    """Una alerta emitida para una entidad, tipo y fecha de ejecución."""

    __tablename__ = "alert_records"

    id = db.Column(db.Integer, primary_key=True)
    alert_type = db.Column(db.String(60), nullable=False)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.String(60), nullable=False)
    run_date = db.Column(db.Date, nullable=False)
    notification_id = db.Column(
        db.Integer, db.ForeignKey("notifications.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "entity_type",
            "entity_id",
            "alert_type",
            "run_date",
            name="uq_alert_entity_type_date",
        ),
    )
