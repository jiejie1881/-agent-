"""Daily fixed driver attendance with explicit dated overrides."""
from alembic import op
import sqlalchemy as sa

revision = "20261009_20"
down_revision = "20261009_19"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("driver_attendances") as batch:
        batch.add_column(sa.Column("override_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "driver_attendance_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("effective_date", sa.Date(), nullable=False, index=True),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("driver_id", "effective_date", "period", name="uq_driver_fixed_attendance"),
        sa.CheckConstraint("period IN ('MORNING', 'AFTERNOON')", name="ck_driver_fixed_attendance_period"),
    )


def downgrade():
    # 回退会失去固定设置，原始当天调整记录仍保留；先备份。
    op.drop_table("driver_attendance_rules")
    with op.batch_alter_table("driver_attendances") as batch:
        batch.drop_column("override_enabled")
