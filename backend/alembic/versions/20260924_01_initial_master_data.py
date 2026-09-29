"""Create phase-one master data tables."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "terrains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamp_columns(),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_terrains_code", "terrains", ["code"])

    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamp_columns(),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_routes_code", "routes", ["code"])

    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(100), nullable=True),
        sa.Column("contact_phone", sa.String(30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamp_columns(),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_stores_code", "stores", ["code"])

    op.create_table(
        "vehicle_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("min_load", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_load", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamp_columns(),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_vehicle_types_code", "vehicle_types", ["code"])

    op.create_table(
        "route_terrain_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("terrain_id", sa.Integer(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["terrain_id"], ["terrains.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("route_id", "effective_date", name="uq_route_terrain_date"),
    )
    op.create_index("ix_route_terrain_configs_route_id", "route_terrain_configs", ["route_id"])
    op.create_index("ix_route_terrain_configs_terrain_id", "route_terrain_configs", ["terrain_id"])
    op.create_index("ix_route_terrain_configs_effective_date", "route_terrain_configs", ["effective_date"])

    op.create_table(
        "store_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("store_id", "route_id", name="uq_store_route"),
    )
    op.create_index("ix_store_routes_store_id", "store_routes", ["store_id"])
    op.create_index("ix_store_routes_route_id", "store_routes", ["route_id"])

    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("plate_number", sa.String(20), nullable=False),
        sa.Column("vehicle_type_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["vehicle_type_id"], ["vehicle_types.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("plate_number"),
    )
    op.create_index("ix_vehicles_code", "vehicles", ["code"])
    op.create_index("ix_vehicles_plate_number", "vehicles", ["plate_number"])
    op.create_index("ix_vehicles_vehicle_type_id", "vehicles", ["vehicle_type_id"])


def downgrade() -> None:
    op.drop_table("vehicles")
    op.drop_table("store_routes")
    op.drop_table("route_terrain_configs")
    op.drop_table("vehicle_types")
    op.drop_table("stores")
    op.drop_table("routes")
    op.drop_table("terrains")

