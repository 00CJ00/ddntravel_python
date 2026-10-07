"""Auditoría de DDN Travel (RN-05, RF-19).

``record()`` añade una fila de ``AuditLog`` a la **transacción abierta** (no
confirma por sí solo): así el cambio y su auditoría se confirman o revierten
juntos. La IP y el navegador se toman de la petición real; ``ProxyFix`` ya deja
la IP del cliente en ``request.remote_addr``.
"""
from __future__ import annotations

from flask import has_request_context, request

from .extensions import db
from . import models as m
from .repositories.base import coerce_id


def snapshot(entity):
    """Estado serializable de una entidad (``dict``) o ``None``."""
    if entity is None:
        return None
    if isinstance(entity, dict):
        return dict(entity)
    to_dict = getattr(entity, "to_dict", None)
    return to_dict() if callable(to_dict) else None


def _request_meta():
    """Devuelve ``(ip, user_agent)`` de la petición actual, o ``(None, None)``."""
    if not has_request_context():
        return None, None
    ip = request.remote_addr or None
    agent = request.user_agent.string if request.user_agent else None
    if agent:
        agent = agent[:300]
    return ip, agent


def record(action, module, entity=None, before=None, after=None, *, user=None,
           user_id=None, user_name=None, user_role=None, details=None,
           entity_type=None, entity_id=None):
    """Registra una acción de auditoría en la sesión/transacción actual.

    Parámetros
    ----------
    action, module: texto de la acción y módulo afectado.
    entity: entidad ORM afectada (de la que se derivan tipo, id y snapshot).
    before, after: snapshots previo y posterior (``dict``); si ``after`` es
        ``None`` se calcula desde ``entity``.
    user: usuario ORM que ejecuta la acción (alternativa a ``user_*``).
    """
    if user is not None:
        user_id = getattr(user, "id", user_id)
        user_name = getattr(user, "name", user_name)
        user_role = getattr(user, "role", user_role)
    if entity is not None:
        entity_type = entity_type or entity.__class__.__name__
        if entity_id is None:
            entity_id = getattr(entity, "id", None)

    ip, agent = _request_meta()
    log = m.AuditLog(
        action=action,
        module=module,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after if after is not None else snapshot(entity),
        user_id=coerce_id(user_id),
        user_name=user_name,
        user_role=user_role or "system",
        ip_address=ip,
        user_agent=agent,
        details=details,
    )
    db.session.add(log)
    return log
