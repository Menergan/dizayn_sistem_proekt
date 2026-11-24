from alembic import op
import sqlalchemy as sa


revision = "20261124_02"
down_revision = "20261124_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payment_operations", sa.Column("amount", sa.Numeric(precision=14, scale=2)))
    op.add_column("payment_operations", sa.Column("status", sa.String(length=16)))
    op.add_column("payment_operations", sa.Column("external_operation_id", sa.String(length=160)))
    op.add_column("payment_operations", sa.Column("external_response", sa.JSON()))
    op.execute("UPDATE payment_operations SET amount = 0, status = 'PENDING'")
    op.alter_column("payment_operations", "amount", nullable=False)
    op.alter_column("payment_operations", "status", nullable=False)


def downgrade() -> None:
    op.drop_column("payment_operations", "external_response")
    op.drop_column("payment_operations", "external_operation_id")
    op.drop_column("payment_operations", "status")
    op.drop_column("payment_operations", "amount")
