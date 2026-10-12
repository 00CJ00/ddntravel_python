"""P3 soft delete: deleted_at en catalog

Revision ID: 7502a2a67959
Revises: dd6986e58c40
Create Date: 2026-10-09 15:43:28.009781

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7502a2a67959'
down_revision = 'dd6986e58c40'
branch_labels = None
depends_on = None


def upgrade():
    # Soft delete (baja lógica) en las entidades de catálogo con historial
    # (RN-04 / fase P3): Paquete, Hotel y Vuelo. Cliente y Reserva ya lo tenían.
    for table in ("packages", "hotels", "flights"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for table in ("packages", "hotels", "flights"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("deleted_at")
