"""Tests de notificaciones por usuario y correo (RF-13) — Fase P6."""
import logging

from app import models as m
from app.extensions import db
from conftest import ADMIN_EMAIL, CLIENT_EMAIL, EMPLOYEE_EMAIL


def _users():
    return (
        m.User.query.filter_by(email=ADMIN_EMAIL).one(),
        m.User.query.filter_by(email=EMPLOYEE_EMAIL).one(),
        m.Client.query.filter_by(email=CLIENT_EMAIL).one(),
    )


def _create_booking(store, admin, client, *, initial_payment=0):
    return store.create_booking(
        admin,
        client_id=client.id,
        client_name=client.name,
        client_email=client.email,
        destination_name="Punta Cana",
        travelers=2,
        total_price=1000,
        initial_payment=initial_payment,
    )


def _configure_mail(app):
    app.config.update(
        MAIL_SERVER="smtp.test.invalid",
        MAIL_PORT=2525,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_DEFAULT_SENDER="no-reply@example.test",
    )


def test_lectura_de_notificaciones_es_por_usuario(store):
    admin, employee, _client = _users()
    notification = m.Notification(
        title="Aviso de prueba",
        message="Solo se marca como leída para quien la consulta.",
        visible_roles=["admin", "employee"],
        read=False,
    )
    db.session.add(notification)
    db.session.commit()

    store.mark_notification_as_read(admin, notification.id)
    store.mark_notification_as_read(admin, notification.id)

    assert notification.id in store.notification_read_ids(admin.id)
    assert notification.id not in store.notification_read_ids(employee.id)
    assert m.NotificationRead.query.filter_by(
        notification_id=notification.id, user_id=admin.id).count() == 1


def test_marcar_todas_respeta_visibilidad_por_rol(store):
    _admin, employee, _client = _users()
    visible = m.Notification(
        title="Aviso interno",
        message="Visible para empleado.",
        visible_roles=["admin", "employee"],
    )
    hidden = m.Notification(
        title="Aviso de administrador",
        message="No visible para empleado.",
        visible_roles=["admin"],
    )
    db.session.add_all([visible, hidden])
    db.session.commit()

    store.mark_all_notifications_as_read(employee)
    read_ids = store.notification_read_ids(employee.id)

    assert visible.id in read_ids
    assert hidden.id not in read_ids


def test_emails_de_reserva_pago_y_cancelacion_son_deterministas(
    app, store, monkeypatch
):
    import app.email_service as email_service

    _configure_mail(app)
    sent = []
    monkeypatch.setattr(email_service.mail, "send", sent.append)
    admin, _employee, client = _users()

    result = _create_booking(store, admin, client)
    assert result["success"]
    booking = result["booking"]
    payment = store.register_payment(admin, booking.id, 1000, "Tarjeta de Crédito")
    assert payment["success"]
    assert store.cancel_booking(admin, booking.id, "Cambio de planes")

    assert len(sent) == 3
    messages = {message.subject: message for message in sent}
    assert "está confirmada." in messages["Reserva confirmada — DDN Travel"].body
    assert "Monto: $1,000.00 USD" in messages["Pago recibido — DDN Travel"].body
    assert "Cambio de planes" in messages["Reserva cancelada — DDN Travel"].body
    assert all(message.recipients == [client.email] for message in sent)


def test_fallo_smtp_no_impide_confirmar_reserva(app, store, monkeypatch, caplog):
    import app.email_service as email_service

    _configure_mail(app)

    def fail_send(_message):
        raise RuntimeError("SMTP de prueba no disponible")

    monkeypatch.setattr(email_service.mail, "send", fail_send)
    caplog.set_level(logging.ERROR)
    admin, _employee, client = _users()

    result = _create_booking(store, admin, client, initial_payment=1000)

    assert result["success"]
    assert result["booking"].status == "Confirmada"
    assert "No se pudo enviar el email" in caplog.text


def test_sin_smtp_registra_evento_sin_intentar_conexion(app, store, caplog):
    import app.email_service as email_service

    app.config.update(MAIL_SERVER=None, MAIL_DEFAULT_SENDER=None)
    caplog.set_level(logging.INFO)
    admin, _employee, client = _users()

    result = _create_booking(store, admin, client, initial_payment=1000)

    assert result["success"]
    assert "configura MAIL_SERVER y MAIL_DEFAULT_SENDER" in caplog.text
    assert email_service.EMAIL_EVENTS["booking_confirmed"][1] == (
        "emails/booking_confirmed.txt")
