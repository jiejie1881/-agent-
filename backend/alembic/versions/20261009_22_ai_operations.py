"""Transactional batch receipts and immutable quality snapshots."""
from alembic import op
import sqlalchemy as sa
revision = "20261009_22"
down_revision = "20261009_21"
branch_labels = depends_on = None

def upgrade():
    op.create_table("demand_batch_receipts", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("demand_ids", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("actor_id", "request_key", name="uq_demand_batch_actor_key"))
    op.create_table("dispatch_quality_reports", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("dispatch_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_version", sa.String(50), nullable=False), sa.Column("basis_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False), sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_dispatch_quality_reports_plan_id", "dispatch_quality_reports", ["plan_id"])

def downgrade():
    op.drop_index("ix_dispatch_quality_reports_plan_id", table_name="dispatch_quality_reports")
    op.drop_table("dispatch_quality_reports")
    op.drop_table("demand_batch_receipts")
