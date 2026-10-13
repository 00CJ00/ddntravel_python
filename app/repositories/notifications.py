"""Repositorio de notificaciones (RF-13)."""
from __future__ import annotations

from sqlalchemy import desc

from .. import models as m
from .base import all_of, get, save


def list_notifications():
    return all_of(m.Notification, desc(m.Notification.created_at))


def get_notification(ident):
    return get(m.Notification, ident)


def create_notification(title, message, ntype="info", link_tab=None, visible_roles=None,
                        date_text="Justo ahora", event_key=None):
    return save(m.Notification(
        title=title, message=message, type=ntype, date=date_text, read=False,
        link_tab=link_tab, visible_roles=visible_roles, event_key=event_key,
    ))


def get_by_event_key(event_key):
    """Devuelve la notificación con esa clave anti-duplicados o ``None``."""
    if not event_key:
        return None
    return m.Notification.query.filter_by(event_key=event_key).first()


def get_read(notification_id, user_id):
    """Marca de lectura de un usuario o ``None``."""
    if notification_id is None or user_id is None:
        return None
    return m.NotificationRead.query.filter_by(
        notification_id=notification_id, user_id=user_id).first()


def mark_read_by(notif, user_id) -> None:
    """Registra la lectura de un usuario (idempotente, por usuario)."""
    if user_id is None or get_read(notif.id, user_id) is not None:
        return
    save(m.NotificationRead(notification_id=notif.id, user_id=user_id))


def mark_read(notif, user=None) -> None:
    notif.read = True


def mark_all_read() -> None:
    m.Notification.query.update({m.Notification.read: True}, synchronize_session=False)
