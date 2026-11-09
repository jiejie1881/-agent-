"""Decouple vehicle type identity from configurable load ranges."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_06"
down_revision: str | None = "20260924_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODES = ("FOUR_METER", "BIG_VAN", "SMALL_VAN")


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE vehicle_types SET code = CASE "
            "WHEN name = '四米二' THEN 'FOUR_METER' "
            "WHEN name = '大包' THEN 'BIG_VAN' "
            "WHEN name = '小包' THEN 'SMALL_VAN' "
            "ELSE code END"
        )
    )
    allowed = ", ".join(f"'{code}'" for code in CODES)
    with op.batch_alter_table("vehicle_types") as batch_op:
        batch_op.alter_column(
            "code",
            existing_type=sa.String(length=50),
            type_=sa.String(length=10),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "vehicle_type_code",
            f"code IN ({allowed})",
        )


def downgrade() -> None:
    with op.batch_alter_table("vehicle_types") as batch_op:
        batch_op.drop_constraint("vehicle_type_code", type_="check")
        batch_op.alter_column(
            "code",
            existing_type=sa.String(length=10),
            type_=sa.String(length=50),
            existing_nullable=False,
        )

