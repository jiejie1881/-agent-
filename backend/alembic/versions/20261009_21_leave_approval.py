"""Leave approval and dated, confirmed substitution history."""
from alembic import op
import sqlalchemy as sa

revision = "20261009_21"
down_revision = "20261009_20"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("driver_leaves") as batch:
        batch.drop_constraint("ck_leave_status", type_="check")
        batch.add_column(sa.Column("leave_type", sa.String(50), nullable=False, server_default="OTHER"))
        batch.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("review_remark", sa.String(1000), nullable=True))
        batch.create_foreign_key("fk_leave_reviewer", "users", ["reviewed_by"], ["id"], ondelete="RESTRICT")
    op.execute("UPDATE driver_leaves SET status='APPROVED', review_remark='迁移前已确认记录；非新审批操作' WHERE status='CONFIRMED'")
    with op.batch_alter_table("driver_leaves") as batch:
        batch.create_check_constraint("ck_leave_status", "status IN ('PENDING','APPROVED','REJECTED','CANCELLED')")
    op.create_table(
        "driver_substitutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("leave_request_id", sa.Integer(), sa.ForeignKey("driver_leaves.id", ondelete="RESTRICT"), index=True),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("substitute_driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("active_vehicle_id", sa.Integer()),
        sa.Column("active_driver_id", sa.Integer()),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('PENDING','CONFIRMED','CANCELLED')", name="ck_substitution_status"),
        sa.CheckConstraint("period IN ('MORNING','AFTERNOON')", name="ck_substitution_period"),
        sa.UniqueConstraint("date", "period", "active_vehicle_id", name="uq_substitution_vehicle"),
        sa.UniqueConstraint("date", "period", "active_driver_id", name="uq_substitution_driver"),
        sa.CheckConstraint("(status = 'CONFIRMED' AND active_vehicle_id IS NOT NULL AND active_driver_id IS NOT NULL AND active_vehicle_id = vehicle_id AND active_driver_id = substitute_driver_id) OR (status != 'CONFIRMED' AND active_vehicle_id IS NULL AND active_driver_id IS NULL)", name="ck_substitution_active"),
    )
    # Preserve pre-upgrade substitutions without claiming a new ADMIN approval occurred.
    op.execute("INSERT INTO driver_substitutions (vehicle_id,original_driver_id,substitute_driver_id,date,period,status,active_vehicle_id,active_driver_id,created_at,updated_at) SELECT vehicle_id,original_driver_id,driver_id,date,period,'CONFIRMED',vehicle_id,driver_id,created_at,updated_at FROM driver_schedules WHERE kind='SUBSTITUTE' AND status='ACTIVE' AND original_driver_id IS NOT NULL")


def downgrade():
    # Lossy for new approval/proposal history: only use after backup in test environments.
    op.drop_table("driver_substitutions")
    with op.batch_alter_table("driver_leaves") as batch:
        batch.drop_constraint("ck_leave_status", type_="check")
    op.execute("UPDATE driver_leaves SET status=CASE WHEN status='APPROVED' THEN 'CONFIRMED' ELSE 'CANCELLED' END")
    with op.batch_alter_table("driver_leaves") as batch:
        batch.drop_constraint("fk_leave_reviewer", type_="foreignkey")
        for column in ("leave_type", "reviewed_by", "reviewed_at", "review_remark"):
            batch.drop_column(column)
        batch.create_check_constraint("ck_leave_status", "status IN ('CONFIRMED','CANCELLED')")
