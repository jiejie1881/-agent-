"""Durable driver stop operation receipts, committed with business and audit."""
import sqlalchemy as sa

from alembic import op

revision='20261015_28'
down_revision='20261014_27'
branch_labels=depends_on=None


def upgrade():
    op.create_table('driver_operation_receipts',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('actor_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('request_key',sa.String(32),nullable=False),
        sa.Column('operation',sa.String(24),nullable=False),
        sa.Column('stop_id',sa.Integer(),sa.ForeignKey('dispatch_order_details.id',ondelete='CASCADE'),nullable=False),
        sa.Column('request_sha256',sa.String(64),nullable=False),
        sa.Column('proof_id',sa.Integer(),sa.ForeignKey('delivery_proofs.id',ondelete='RESTRICT'),nullable=True),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('actor_id','request_key',name='uq_driver_operation_key'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM driver_operation_receipts')).scalar():
        raise RuntimeError('Preserve driver receipts: nonempty downgrade requires coordinated backup/restore')
    op.drop_table('driver_operation_receipts')
