"""Separate default vehicles from actual shift drivers; retain task ownership."""
from alembic import op
import sqlalchemy as sa

revision = "20261009_19"
down_revision = "20261001_18"
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("display_name", sa.String(100)))
    with op.batch_alter_table("dispatch_orders") as batch:
        batch.add_column(sa.Column("actual_driver_id", sa.Integer()))
        batch.add_column(sa.Column("driver_username_snapshot", sa.String(100)))
        batch.add_column(sa.Column("driver_name_snapshot", sa.String(100)))
        batch.create_foreign_key("fk_order_actual_driver", "users", ["actual_driver_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_dispatch_orders_actual_driver_id", ["actual_driver_id"])
    op.create_table("driver_attendances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("driver_id", "date", "period", name="uq_driver_attendance_shift"),
        sa.CheckConstraint("period IN ('MORNING', 'AFTERNOON')", name="ck_driver_attendance_period"))
    op.create_table("driver_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("original_driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("date", "period", "vehicle_id", name="uq_schedule_vehicle_shift"),
        sa.UniqueConstraint("date", "period", "driver_id", name="uq_schedule_driver_shift"),
        sa.CheckConstraint("period IN ('MORNING', 'AFTERNOON')", name="ck_schedule_period"),
        sa.CheckConstraint("kind IN ('NORMAL', 'SUBSTITUTE')", name="ck_schedule_kind"))
    op.create_table("driver_leaves",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("start_date", sa.Date(), nullable=False, index=True),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("remark", sa.String(1000)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("start_date <= end_date", name="ck_leave_date_range"),
        sa.CheckConstraint("period IN ('MORNING', 'AFTERNOON', 'ALL_DAY')", name="ck_leave_period"),
        sa.CheckConstraint("status IN ('CONFIRMED', 'CANCELLED')", name="ck_leave_status"))
    # 仅保存迁移时可确定的当前绑定，不伪造过去的真实执行信息。
    op.execute(sa.text("UPDATE dispatch_orders SET actual_driver_id = (SELECT driver_user_id FROM vehicles WHERE vehicles.id = dispatch_orders.vehicle_id)"))
    op.execute(sa.text("UPDATE dispatch_orders SET driver_username_snapshot = (SELECT username FROM users WHERE users.id = dispatch_orders.actual_driver_id)"))


def downgrade():
    # 会丢失新增排班与执行人快照，仅用于回退测试；正式环境先备份。
    op.drop_table("driver_leaves")
    op.drop_table("driver_schedules")
    op.drop_table("driver_attendances")
    with op.batch_alter_table("dispatch_orders") as batch:
        batch.drop_index("ix_dispatch_orders_actual_driver_id")
        batch.drop_constraint("fk_order_actual_driver", type_="foreignkey")
        batch.drop_column("driver_name_snapshot")
        batch.drop_column("driver_username_snapshot")
        batch.drop_column("actual_driver_id")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("display_name")
