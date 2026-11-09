"""Add vehicle type terrain permissions for dispatch validation."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_03"
down_revision: str | None = "20260924_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_type_terrain_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_type_id", sa.Integer(), nullable=False),
        sa.Column("terrain_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_type_id"], ["vehicle_types.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["terrain_id"], ["terrains.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "vehicle_type_id", "terrain_id", name="uq_vehicle_type_terrain"
        ),
    )
    op.create_index(
        "ix_vehicle_type_terrain_permissions_vehicle_type_id",
        "vehicle_type_terrain_permissions",
        ["vehicle_type_id"],
    )
    op.create_index(
        "ix_vehicle_type_terrain_permissions_terrain_id",
        "vehicle_type_terrain_permissions",
        ["terrain_id"],
    )


def downgrade() -> None:
    op.drop_table("vehicle_type_terrain_permissions")

