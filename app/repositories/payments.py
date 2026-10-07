"""Repositorio de pagos (RF-11)."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy import desc

from .. import models as m
from .base import all_of, get, save, to_decimal


def list_payments():
    return all_of(m.Payment, desc(m.Payment.created_at))


def get_payment(ident):
    return get(m.Payment, ident)


def create_payment(booking_id, amount, method, reference="", status="Completado",
                   kind="pago", card_last4=None) -> m.Payment:
    """Inserta el pago; recibo y factura se derivan de la PK (únicos)."""
    payment = m.Payment(
        booking_id=booking_id, kind=kind, amount=to_decimal(amount), method=method,
        reference=reference or None, status=status, card_last4=card_last4,
        receipt_number=f"TMP-{uuid4().hex}",
    )
    save(payment)
    year = date.today().year
    payment.receipt_number = f"REC-{year}-{payment.id:05d}"
    payment.invoice_number = f"FAC-DDN-{payment.id:05d}"
    return payment
