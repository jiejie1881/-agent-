"""Allow business-defined vehicle type codes while preserving legacy identities."""
from alembic import op
import sqlalchemy as sa
revision='20261014_27'
down_revision='20261014_26'
branch_labels=depends_on=None
def upgrade():
    with op.batch_alter_table('vehicle_types') as batch:
        batch.drop_constraint('vehicle_type_code',type_='check')
        batch.alter_column('code',existing_type=sa.String(10),type_=sa.String(50),existing_nullable=False)
def downgrade():
    connection=op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM vehicle_types WHERE code NOT IN ('FOUR_METER','BIG_VAN','SMALL_VAN')")).scalar():
        raise RuntimeError('Downgrade would reject custom vehicle types; preserve data and resolve explicitly before rollback')
    with op.batch_alter_table('vehicle_types') as batch:
        batch.alter_column('code',existing_type=sa.String(50),type_=sa.String(10),existing_nullable=False)
        batch.create_check_constraint('vehicle_type_code',"code IN ('FOUR_METER','BIG_VAN','SMALL_VAN')")
