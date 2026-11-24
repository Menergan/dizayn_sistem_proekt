"""Participant 4 durable lifecycle journal."""
from alembic import op
import sqlalchemy as sa

revision = "20261125_03"
down_revision = "20261124_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("rental_lifecycle",
        sa.Column("rental_id", sa.Uuid(), sa.ForeignKey("rentals.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("offer_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("station_operation_id", sa.String(160), nullable=False, unique=True))


def downgrade():
    op.drop_table("rental_lifecycle")
