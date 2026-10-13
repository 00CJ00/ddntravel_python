"""P6: clave anti-duplicados en notificaciones (RF-13).

Agrega ``notifications.event_key`` (UNIQUE, nullable) para no repetir la
notificación de un mismo evento (confirmación, pago, cancelación, alertas).
Compatible con SQLite (batch) y PostgreSQL. Los NULL no colisionan en
ningún motor, así que las notificaciones operativas existentes no se ven
afectadas.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e6ccd1447029'
down_revision = 'b7a4d915c2f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("event_key", sa.String(length=120), nullable=True))
        batch_op.create_unique_constraint("uq_notifications_event_key", ["event_key"])


def downgrade() -> None:
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_constraint("uq_notifications_event_key", type_="unique")
        batch_op.drop_column("event_key")
