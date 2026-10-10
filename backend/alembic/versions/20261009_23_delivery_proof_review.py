"""Receipt review history and non-destructive photo replacements."""
from alembic import op
import sqlalchemy as sa

revision = "20261009_23"
down_revision = "20261009_22"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("delivery_proofs") as batch:
        batch.add_column(sa.Column("review_status", sa.String(8), nullable=False, server_default="PENDING"))
        batch.add_column(sa.Column("replaces_proof_id", sa.Integer(), nullable=True))
        batch.create_check_constraint("delivery_proof_review_status", "review_status IN ('PENDING','APPROVED','REJECTED')")
        batch.create_foreign_key("fk_delivery_proof_replaces", "delivery_proofs", ["replaces_proof_id"], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("uq_delivery_proof_replaces", ["replaces_proof_id"])
    op.create_table("delivery_proof_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proof_id", sa.Integer(), sa.ForeignKey("delivery_proofs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reviewer_username", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("proof_id", name="uq_delivery_proof_review_once"),
        sa.CheckConstraint("decision IN ('PENDING','APPROVED','REJECTED')", name="delivery_proof_review_decision"),
    )
    op.create_index("ix_delivery_proof_reviews_proof_id", "delivery_proof_reviews", ["proof_id"])


def downgrade():
    # Downgrade loses review/replacement history, but preserves every image and signature.
    op.drop_table("delivery_proof_reviews")
    with op.batch_alter_table("delivery_proofs") as batch:
        batch.drop_constraint("uq_delivery_proof_replaces", type_="unique")
        batch.drop_constraint("fk_delivery_proof_replaces", type_="foreignkey")
        batch.drop_constraint("delivery_proof_review_status", type_="check")
        batch.drop_column("replaces_proof_id")
        batch.drop_column("review_status")
