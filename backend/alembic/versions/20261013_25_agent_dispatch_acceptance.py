"""Agent draft provenance, replay guard and date serialization row."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_25"
down_revision = "20261010_24"
branch_labels = depends_on = None


def upgrade():
    op.create_table("dispatch_date_guards",
                    sa.Column("delivery_date", sa.Date(), primary_key=True))
    op.create_table(
        "agent_dispatch_plan_sources",
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("dispatch_plans.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("receipt_nonce_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("candidate_sha256", sa.String(64), nullable=False),
        sa.Column("generated_snapshot_version", sa.String(64), nullable=False),
        sa.Column("post_save_snapshot_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("accepted_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_dispatch_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("receipt_nonce_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("dispatch_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_id", "operation", "idempotency_key", name="uq_agent_dispatch_operation_key"),
    )


def downgrade():
    op.drop_table("agent_dispatch_operations")
    op.drop_table("agent_dispatch_plan_sources")
    op.drop_table("dispatch_date_guards")
