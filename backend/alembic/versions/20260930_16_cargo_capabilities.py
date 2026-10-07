"""Add cargo categories, demand transport attributes, and vehicle capabilities."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_16"
down_revision: str | None = "20260930_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "cargo_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("ix_cargo_categories_code", "cargo_categories", ["code"], unique=True)
    cargo_table = sa.table(
        "cargo_categories",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        cargo_table,
        [
            {"code": "NORMAL", "name": "常温商品", "description": None, "is_active": True},
            {"code": "FRESH", "name": "生鲜", "description": None, "is_active": True},
            {"code": "FROZEN", "name": "冷冻品", "description": None, "is_active": True},
            {"code": "BULK", "name": "大宗货物", "description": None, "is_active": True},
        ],
    )

    op.create_table(
        "vehicle_type_cargo_capabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_type_id", sa.Integer(), nullable=False),
        sa.Column("cargo_category_id", sa.Integer(), nullable=False),
        sa.Column("is_allowed", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("min_temperature", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_temperature", sa.Numeric(5, 2), nullable=True),
        *timestamp_columns(),
        sa.CheckConstraint(
            "(min_temperature IS NULL AND max_temperature IS NULL) OR "
            "(min_temperature IS NOT NULL AND max_temperature IS NOT NULL "
            "AND min_temperature <= max_temperature)",
            name="ck_vehicle_type_cargo_temperature_range",
        ),
        sa.ForeignKeyConstraint(["vehicle_type_id"], ["vehicle_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cargo_category_id"], ["cargo_categories.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("vehicle_type_id", "cargo_category_id", name="uq_vehicle_type_cargo"),
    )
    op.create_index(
        "ix_vehicle_type_cargo_capabilities_vehicle_type_id",
        "vehicle_type_cargo_capabilities", ["vehicle_type_id"],
    )
    op.create_index(
        "ix_vehicle_type_cargo_capabilities_cargo_category_id",
        "vehicle_type_cargo_capabilities", ["cargo_category_id"],
    )
    op.execute(
        "INSERT INTO vehicle_type_cargo_capabilities "
        "(vehicle_type_id, cargo_category_id, is_allowed, created_at, updated_at) "
        "SELECT vt.id, cc.id, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM vehicle_types vt CROSS JOIN cargo_categories cc "
        "WHERE cc.code = 'NORMAL'"
    )

    with op.batch_alter_table("delivery_demands") as batch_op:
        batch_op.add_column(sa.Column("cargo_category_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("priority", sa.String(20), server_default="NORMAL", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "requires_temperature_control", sa.Boolean(),
                server_default=sa.false(), nullable=False,
            )
        )
        batch_op.add_column(sa.Column("min_temperature", sa.Numeric(5, 2), nullable=True))
        batch_op.add_column(sa.Column("max_temperature", sa.Numeric(5, 2), nullable=True))

    op.execute(
        "UPDATE delivery_demands SET cargo_category_id = "
        "(SELECT id FROM cargo_categories WHERE code = 'NORMAL') "
        "WHERE cargo_category_id IS NULL"
    )
    with op.batch_alter_table("delivery_demands") as batch_op:
        batch_op.alter_column("cargo_category_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_delivery_demands_cargo_category_id",
            "cargo_categories", ["cargo_category_id"], ["id"], ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_delivery_demand_temperature_range",
            "requires_temperature_control = 0 OR "
            "(min_temperature IS NOT NULL AND max_temperature IS NOT NULL "
            "AND min_temperature <= max_temperature)",
        )
        batch_op.create_check_constraint(
            "delivery_priority", "priority IN ('NORMAL', 'HIGH', 'URGENT')"
        )
    op.create_index(
        "ix_delivery_demands_cargo_category_id", "delivery_demands", ["cargo_category_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_demands_cargo_category_id", table_name="delivery_demands")
    with op.batch_alter_table("delivery_demands") as batch_op:
        batch_op.drop_constraint("delivery_priority", type_="check")
        batch_op.drop_constraint("ck_delivery_demand_temperature_range", type_="check")
        batch_op.drop_constraint("fk_delivery_demands_cargo_category_id", type_="foreignkey")
        batch_op.drop_column("max_temperature")
        batch_op.drop_column("min_temperature")
        batch_op.drop_column("requires_temperature_control")
        batch_op.drop_column("priority")
        batch_op.drop_column("cargo_category_id")
    op.drop_table("vehicle_type_cargo_capabilities")
    op.drop_table("cargo_categories")
