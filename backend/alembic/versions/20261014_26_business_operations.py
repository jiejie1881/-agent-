"""Business master attributes, persisted import previews and exception cases."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_26"
down_revision = "20261013_25"
branch_labels = depends_on = None


def upgrade():
    op.add_column("stores", sa.Column("delivery_region", sa.String(100)))
    for column in (sa.Column("start_address",sa.String(255)),sa.Column("end_address",sa.String(255)),
                   sa.Column("geographic_notes",sa.Text()),sa.Column("distance_km",sa.Numeric(10,2)),
                   sa.Column("duration_minutes",sa.Integer()),sa.Column("route_data_source",sa.String(100))):
        op.add_column("routes",column)
    for column in (sa.Column("organization",sa.String(100)),sa.Column("rated_load",sa.Numeric(10,2)),
                   sa.Column("daily_trip_limit",sa.Integer()),sa.Column("allowed_route_ids",sa.JSON()),
                   sa.Column("operating_status",sa.String(20),nullable=False,server_default="ACTIVE")):
        op.add_column("vehicles",column)
    timestamps=lambda:[sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now())]
    op.create_table("business_imports",sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("actor_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("kind",sa.String(20),nullable=False),sa.Column("file_sha256",sa.String(64),nullable=False),
        sa.Column("status",sa.String(20),nullable=False),sa.Column("rows",sa.JSON(),nullable=False),
        sa.Column("errors",sa.JSON(),nullable=False),sa.Column("result_ids",sa.JSON(),nullable=False),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),*timestamps(),
        sa.UniqueConstraint("actor_id","kind","file_sha256",name="uq_business_import_file"))
    op.create_index("ix_business_imports_actor_id","business_imports",["actor_id"])
    op.create_table("exception_cases",sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("source_key",sa.String(100),nullable=False),sa.Column("category",sa.String(40),nullable=False),
        sa.Column("reason",sa.Text(),nullable=False),sa.Column("status",sa.String(20),nullable=False),
        sa.Column("responsible_user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT")),
        sa.Column("resolution",sa.Text()),sa.Column("revision",sa.Integer(),nullable=False),*timestamps(),
        sa.UniqueConstraint("source_key",name="uq_exception_source"))
    op.create_table("exception_case_events",sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("case_id",sa.Integer(),sa.ForeignKey("exception_cases.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("actor_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("before_status",sa.String(20)),sa.Column("after_status",sa.String(20),nullable=False),
        sa.Column("note",sa.Text()),*timestamps())
    op.create_index("ix_exception_case_events_case_id","exception_case_events",["case_id"])


def downgrade():
    op.drop_table("exception_case_events")
    op.drop_table("exception_cases")
    op.drop_table("business_imports")
    for table,columns in (("vehicles",["operating_status","allowed_route_ids","daily_trip_limit","rated_load","organization"]),
                          ("routes",["route_data_source","duration_minutes","distance_km","geographic_notes","end_address","start_address"]),
                          ("stores",["delivery_region"])):
        for column in columns:op.drop_column(table,column)
