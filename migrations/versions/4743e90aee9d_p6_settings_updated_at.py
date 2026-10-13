"""P6: marca temporal en settings (resultados predictivos con fecha).

Agrega ``settings.updated_at`` (UTC, se actualiza en cada escritura) para
saber cuándo se generó el último análisis predictivo. Reversible y
compatible con SQLite (batch) y PostgreSQL.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '4743e90aee9d'
down_revision = 'e6ccd1447029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
