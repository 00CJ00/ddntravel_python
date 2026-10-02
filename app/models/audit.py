"""Auditoría del sistema (RN-05, RF-19)."""
from __future__ import annotations

from sqlalchemy import event

from ..extensions import db
from .base import BaseEntity, utcnow


class AuditLog(BaseEntity, db.Model):
    """Registro de solo inserción de las operaciones del sistema (RN-05)."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    user_name = db.Column(db.String(120))
    user_role = db.Column(db.String(20))
    action = db.Column(db.String(80), index=True)
    module = db.Column(db.String(80), index=True)
    entity_type = db.Column(db.String(60))
    entity_id = db.Column(db.String(60))
    before = db.Column(db.JSON)
    after = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(300))
    details = db.Column(db.Text)

    def describe(self) -> str:
        return f"[{self.timestamp}] {self.action}"


# RN-05: la auditoría es de solo inserción; ningún camino actualiza ni borra.
#
# IMPORTANTE: estos guards ORM (``before_update``/``before_delete``) solo cubren
# operaciones por instancia (``db.session.delete(obj)``, cambios de atributos).
# NO protegen contra un borrado masivo con ``Query.delete()`` (bulk delete), que
# se salta los eventos del mapper. La protección real contra la pérdida del
# historial es la exclusión explícita de ``AuditLog`` en
# ``app/seed.py::clear_database()``. Si añades otro borrado masivo en el futuro,
# debes excluir también esta tabla allí.
@event.listens_for(AuditLog, "before_update")
def _audit_no_update(mapper, connection, target):  # pragma: no cover - guarda defensiva
    raise ValueError("Los registros de auditoría son de solo inserción (no se actualizan).")


@event.listens_for(AuditLog, "before_delete")
def _audit_no_delete(mapper, connection, target):  # pragma: no cover - guarda defensiva
    raise ValueError("Los registros de auditoría son de solo inserción (no se eliminan).")
