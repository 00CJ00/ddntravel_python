"""Repositorio de notificaciones (RF-13)."""
from __future__ import annotations

from sqlalchemy import desc

from .. import models as m
from ..extensions import db
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


def read_ids_for_user(user_id) -> set[int]:
    return {
        row.notification_id
        for row in m.NotificationRead.query.filter_by(user_id=user_id).all()
    }


def _visible_to_role(notif, role) -> bool:
    return notif.visible_roles is None or role in notif.visible_roles


def mark_read(notif, user_id) -> None:
    if user_id is None:
        return
    existing = m.NotificationRead.query.filter_by(
        notification_id=notif.id, user_id=user_id).first()
    if existing is None:
        save(m.NotificationRead(notification_id=notif.id, user_id=user_id))


def mark_all_read(user_id, role) -> None:
    if user_id is None:
        return
    already_read = read_ids_for_user(user_id)
    for notif in list_notifications():
        if _visible_to_role(notif, role) and notif.id not in already_read:
            db.session.add(m.NotificationRead(
                notification_id=notif.id,
                user_id=user_id,
            ))
