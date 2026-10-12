"""P4: reembolso enlazado al pago original y referencia única por reserva.

Agrega ``payments.original_payment_id`` (FK autorreferenciada al pago anulado
que originó el reembolso) y la restricción ``UNIQUE(booking_id, reference)``
que impide el doble envío del mismo pago. Compatible con SQLite (batch) y
PostgreSQL. No elimina ni modifica registros históricos: antes de crear la
restricción se comprueba que no existan duplicados y se aborta con un error
claro si los hay.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '430e52d52ac7'
down_revision = 'dd6986e58c40'
branch_labels = None
depends_on = None


def _duplicados(connection) -> list:
    """Pares (booking_id, reference) repetidos con referencia no nula."""
    return list(connection.execute(sa.text(
        "SELECT booking_id, reference, COUNT(*) AS n FROM payments "
        "WHERE reference IS NOT NULL "
        "GROUP BY booking_id, reference HAVING COUNT(*) > 1"
    )).fetchall())


def upgrade() -> None:
    connection = op.get_bind()
    duplicados = _duplicados(connection)
    if duplicados:
        detalle = ", ".join(f"(reserva={b}, ref={r})" for b, r, _ in duplicados[:10])
        raise RuntimeError(
            "No se puede crear UNIQUE(booking_id, reference): hay pagos "
            f"históricos duplicados: {detalle}. Resuélvelos sin borrar "
            "registros antes de migrar.")

    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("original_payment_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_payments_original_payment", "payments",
            ["original_payment_id"], ["id"])
        batch_op.create_unique_constraint(
            "uq_payments_booking_reference", ["booking_id", "reference"])


def downgrade() -> None:
    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_payments_booking_reference", type_="unique")
        batch_op.drop_constraint("fk_payments_original_payment", type_="foreignkey")
        batch_op.drop_column("original_payment_id")
