from alembic import op
import sqlalchemy as sa


revision = "20261124_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("station_id", sa.String(length=128), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_per_hour", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("free_period_min", sa.Integer(), nullable=False),
        sa.Column("deposit", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rentals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("start_station_id", sa.String(length=128), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_per_hour", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("free_period_min", sa.Integer(), nullable=False),
        sa.Column("deposit", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("powerbank_id", sa.String(length=128)),
        sa.Column("finish_station_id", sa.String(length=128)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2)),
        sa.Column("delete_after", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rentals_active_powerbank", "rentals", ["powerbank_id", "status"])
    op.create_index("ix_rentals_user_id", "rentals", ["user_id"])
    op.create_index("ix_rentals_delete_after", "rentals", ["delete_after"])
    op.create_table(
        "payment_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rental_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("rental_id", "operation_type", name="uq_payment_operations_rental_operation"),
    )
    op.create_table(
        "station_events",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("station_id", sa.String(length=128), nullable=False),
        sa.Column("powerbank_id", sa.String(length=128), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rental_id", sa.Uuid()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rental_id"], ["rentals.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("station_events")
    op.drop_table("payment_operations")
    op.drop_index("ix_rentals_delete_after", table_name="rentals")
    op.drop_index("ix_rentals_user_id", table_name="rentals")
    op.drop_index("ix_rentals_active_powerbank", table_name="rentals")
    op.drop_table("rentals")
    op.drop_table("offers")
