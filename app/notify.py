"""Correo transaccional y plantillas de eventos (RF-13, fase P6).

Usa Flask-Mail cuando hay configuración ``MAIL_*``; en caso contrario usa el
respaldo de consola/log. Nunca lanza: un fallo de correo se registra y se
devuelve ``False``, sin convertir la operación principal en error. No confirma
transacciones (el commit lo centraliza ``DataStore``).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Eventos con plantilla propia: reserva confirmada, pago recibido y
# reserva cancelada. Solo datos del evento (código, destino, importe);
# nunca contraseñas, documentos ni datos de otros clientes.
EVENTS = ("booking_confirmed", "payment_received", "booking_cancelled")


def is_mail_configured(config=None) -> bool:
    """Indica si hay configuración mínima para enviar correo real."""
    if config is None:
        try:
            from flask import current_app
            config = current_app.config
        except RuntimeError:
            return False
    return bool(config.get("MAIL_SERVER")) and bool(config.get("MAIL_DEFAULT_SENDER"))


def render_event(event: str, context: dict) -> tuple[str, str]:
    """Devuelve ``(asunto, cuerpo)`` en texto plano para un evento."""
    booking = context.get("booking_code", "")
    destination = context.get("destination", "")
    if event == "booking_confirmed":
        return (
            f"DDN Travel: tu reserva {booking} está confirmada",
            f"Hola:\n\nTu reserva {booking} con destino {destination} ha sido "
            f"confirmada. Total: ${context.get('total', 0)} USD.\n\n"
            f"Gracias por viajar con DDN Travel.",
        )
    if event == "payment_received":
        return (
            f"DDN Travel: pago recibido para {booking}",
            f"Hola:\n\nHemos recibido tu pago de ${context.get('amount', 0)} USD "
            f"para la reserva {booking} ({destination}). Recibo: "
            f"{context.get('receipt', '')}.\n\nGracias por tu pago.",
        )
    if event == "booking_cancelled":
        return (
            f"DDN Travel: tu reserva {booking} fue cancelada",
            f"Hola:\n\nLa reserva {booking} ({destination}) ha sido cancelada. "
            f"Motivo: {context.get('reason', 'no indicado')}.\n\n"
            f"Contáctanos si deseas reprogramar tu viaje.",
        )
    raise ValueError(f"Evento de correo desconocido: {event}")


def send_event_mail(event: str, to_email: str, context: dict) -> str:
    """Envía el correo del evento o usa el respaldo. Devuelve el backend usado.

    Devuelve ``"smtp"`` si se envió, ``"console"`` si no hay configuración.
    Nunca lanza excepciones.
    """
    from flask import current_app
    try:
        subject, body = render_event(event, context)
    except ValueError:
        log.warning("Plantilla de correo desconocida: %s", event)
        return "console"
    if not (to_email or "").strip():
        return "console"
    if not is_mail_configured(current_app.config):
        log.info("[correo-consola] Para: %s | Asunto: %s\n%s", to_email, subject, body)
        return "console"
    try:
        from flask_mail import Message

        from .extensions import mail
        mail.send(Message(subject=subject, recipients=[to_email.strip()],
                          body=body,
                          sender=current_app.config.get("MAIL_DEFAULT_SENDER")))
        return "smtp"
    except Exception as exc:  # noqa: BLE001 - el correo nunca rompe el flujo
        log.warning("No se pudo enviar el correo a %s: %s", to_email, exc)
        return "console"
