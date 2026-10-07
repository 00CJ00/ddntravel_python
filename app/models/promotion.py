"""Promociones y sus redenciones (RF-12)."""
from __future__ import annotations

from ..extensions import db
from .base import BaseEntity, utcnow


class Promotion(BaseEntity, db.Model):
    """Cupón de descuento."""

    __tablename__ = "promotions"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False, unique=True, index=True)
    title = db.Column(db.String(200))
    discount_percentage = db.Column(db.Integer, default=0)
    valid_until = db.Column(db.Date)
    max_uses = db.Column(db.Integer, default=0)
    current_uses = db.Column(db.Integer, default=0)
    applicable_categories = db.Column(db.JSON, default=list)
    active = db.Column(db.Boolean, default=True, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def is_valid(self) -> bool:
        return bool(self.active) and (self.current_uses or 0) < (self.max_uses or 0)

    def apply_to(self, total_price):
        if not self.is_valid():
            return total_price, 0
        discount = total_price * self.discount_percentage / 100
        return max(0, total_price - discount), discount

    def describe(self) -> str:
        return f"{self.code} (-{self.discount_percentage}%)"


class PromotionRedemption(BaseEntity, db.Model):
    """Registro del uso de una promoción en una reserva (único por reserva)."""

    __tablename__ = "promotion_redemptions"

    id = db.Column(db.Integer, primary_key=True)
    promotion_id = db.Column(db.Integer, db.ForeignKey("promotions.id"), nullable=False, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        db.UniqueConstraint("promotion_id", "booking_id", name="uq_promotion_booking"),
    )
