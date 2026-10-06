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
                        date_text="Justo ahora"):
    return save(m.Notification(
        title=title, message=message, type=ntype, date=date_text, read=False,
        link_tab=link_tab, visible_roles=visible_roles,
    ))


def mark_read(notif, user=None) -> None:
    notif.read = True


def mark_all_read() -> None:
    m.Notification.query.update({m.Notification.read: True}, synchronize_session=False)
