"""Repositorio de promociones y sus redenciones (RF-12)."""
from __future__ import annotations

from sqlalchemy import desc, func

from .. import models as m
from .base import all_of, assign_by_type, get, save


def list_promotions():
    return all_of(m.Promotion, desc(m.Promotion.created_at))


def get_promotion(ident):
    return get(m.Promotion, ident)


def create_promotion(data):
    promo = m.Promotion()
    assign_by_type(promo, data, skip=("id",), allowed=None)
    promo.current_uses = 0
    return save(promo)


def toggle(obj) -> None:
    obj.active = not obj.active


def find_active_by_code(code):
    clean = (code or "").strip().upper()
    if not clean:
        return None
    return (m.Promotion.query
            .filter(func.upper(m.Promotion.code) == clean, m.Promotion.active.is_(True))
            .first())


def register_redemption(promo, booking_id) -> None:
    promo.current_uses = (promo.current_uses or 0) + 1
    save(m.PromotionRedemption(promotion_id=promo.id, booking_id=booking_id))
