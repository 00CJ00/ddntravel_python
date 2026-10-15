"""Envío de correo transaccional para notificaciones (RF-13)."""
from __future__ import annotations

from flask import current_app
from flask_mail import Message

from .extensions import mail

EMAIL_EVENTS = {
    "booking_confirmed": (
        "Reserva confirmada — DDN Travel",
        "emails/booking_confirmed.txt",
    ),
    "payment_received": (
        "Pago recibido — DDN Travel",
        "emails/payment_received.txt",
    ),
    "booking_cancelled": (
        "Reserva cancelada — DDN Travel",
        "emails/booking_cancelled.txt",
    ),
}


def send_booking_email(event: str, booking, *, payment=None, reason="") -> bool:
    """Envía un email tras una mutación ya confirmada en la base de datos."""
    if event not in EMAIL_EVENTS:
        raise ValueError(f"Evento de correo desconocido: {event}")

    recipient = booking.client_email
    if not recipient:
        current_app.logger.warning(
            "No se envió el email %s: la reserva ID %s no tiene email de cliente.",
            event, booking.id)
        return False

    if (not current_app.config.get("MAIL_SERVER")
            or not current_app.config.get("MAIL_DEFAULT_SENDER")):
        current_app.logger.info(
            "Correo %s no enviado: configura MAIL_SERVER y MAIL_DEFAULT_SENDER.",
            event)
        return False

    subject, template = EMAIL_EVENTS[event]
    client = booking.client
    context = {
        "booking_code": booking.booking_code,
        "client_name": getattr(client, "name", None) or "Cliente",
        "destination": booking.destination_name or "Por definir",
        "departure_date": booking.departure_date or "Por definir",
        "return_date": booking.return_date or "Por definir",
        "travelers": booking.travelers or 1,
        "total_price": f"{float(booking.total_price or 0):,.2f}",
        "reason": reason or "No especificado",
    }
    if payment is not None:
        context.update(
            payment_amount=f"{float(payment.amount or 0):,.2f}",
            payment_method=payment.method or "No especificado",
            payment_status=payment.status or "Pendiente",
        )

    try:
        message = Message(
            subject=subject,
            recipients=[recipient],
            body=current_app.jinja_env.get_template(template).render(**context),
        )
        mail.send(message)
    except Exception:
        current_app.logger.exception(
            "No se pudo enviar el email de notificación %s para la reserva ID %s.",
            event, booking.id)
        return False
    return True
