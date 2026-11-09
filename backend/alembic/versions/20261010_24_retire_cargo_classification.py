"""Retire cargo classification without deleting historical transport data."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_24"
down_revision = "20261009_23"
branch_labels = depends_on = None


def upgrade():
    # Keep the FK and all historical values. New demands no longer need a category.
    with op.batch_alter_table("delivery_demands") as batch:
        batch.alter_column("cargo_category_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Never invent an old category or discard newly-created unclassified demands.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM delivery_demands WHERE cargo_category_id IS NULL")).scalar():
        raise RuntimeError("Cannot downgrade: unclassified demands exist. Back up and explicitly resolve them first.")
    with op.batch_alter_table("delivery_demands") as batch:
        batch.alter_column("cargo_category_id", existing_type=sa.Integer(), nullable=False)
