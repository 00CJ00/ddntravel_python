"""Pagos y facturación (RF-11, RN-03)."""
from __future__ import annotations

from sqlalchemy.orm import synonym

from ..extensions import db
from .base import BaseEntity, utcnow

KINDS = ("pago", "reembolso")
PAYMENT_STATUSES = ("Completado", "Pendiente_verificacion", "Anulado")


class Payment(BaseEntity, db.Model):
    """Movimiento de pago o reembolso asociado a una reserva."""

    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), default="pago")
    receipt_number = db.Column(db.String(40), unique=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    method = db.Column(db.String(40), default="Tarjeta de Crédito")
    status = db.Column(db.String(30), default="Completado", index=True)
    reference = db.Column(db.String(80))
    ncf = db.Column(db.String(20), unique=True)
    invoice_number = db.Column(db.String(40))
    card_last4 = db.Column(db.String(4))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    voided_at = db.Column(db.DateTime(timezone=True))
    void_reason = db.Column(db.Text)

    # Alias de compatibilidad con los nombres que usan las plantillas.
    payment_method = synonym("method")
    transaction_ref = synonym("reference")

    @property
    def date(self):
        """Fecha de creación con el formato de visualización anterior."""
        return self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else ""

    def is_ncf_generated(self) -> bool:
        return bool(self.ncf and self.ncf.strip())

    def describe(self) -> str:
        return f"{self.receipt_number} (${self.amount})"
