"""Añade el registro idempotente de alertas automáticas."""
import sqlalchemy as sa
from alembic import op

revision = "a41bd9e7206c"
down_revision = "b7a4d915c2f0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alert_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.String(length=60), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_type", "entity_id", "alert_type", "run_date",
            name="uq_alert_entity_type_date"),
    )
    with op.batch_alter_table("alert_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_alert_records_notification_id"),
            ["notification_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("alert_records", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_alert_records_notification_id"))
    op.drop_table("alert_records")
