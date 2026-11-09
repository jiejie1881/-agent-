"""Add driver role and bind a driver account to one vehicle."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261001_17"
down_revision: str | None = "20260930_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ROLE = sa.Enum(
    "ADMIN", "DISPATCHER", "VIEWER",
    name="user_role", native_enum=False, create_constraint=True,
)
NEW_ROLE = sa.Enum(
    "ADMIN", "DISPATCHER", "VIEWER", "DRIVER",
    name="user_role", native_enum=False, create_constraint=True,
)


def _replace_role_constraint(old_type: sa.Enum, new_type: sa.Enum) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users", recreate="always") as batch_op:
            batch_op.alter_column(
                "role", existing_type=old_type, type_=new_type, nullable=False
            )
        return

    op.drop_constraint("user_role", "users", type_="check")
    op.create_check_constraint(
        "user_role",
        "users",
        "role IN ('ADMIN', 'DISPATCHER', 'VIEWER', 'DRIVER')"
        if new_type is NEW_ROLE
        else "role IN ('ADMIN', 'DISPATCHER', 'VIEWER')",
    )


def upgrade() -> None:
    _replace_role_constraint(OLD_ROLE, NEW_ROLE)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("vehicles", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column("driver_user_id", sa.Integer(), nullable=True)
            )
            batch_op.create_index(
                "ix_vehicles_driver_user_id", ["driver_user_id"], unique=True
            )
            batch_op.create_foreign_key(
                "fk_vehicles_driver_user_id_users",
                "users",
                ["driver_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
        return
    op.add_column("vehicles", sa.Column("driver_user_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_vehicles_driver_user_id", "vehicles", ["driver_user_id"], unique=True
    )
    op.create_foreign_key(
        "fk_vehicles_driver_user_id_users",
        "vehicles",
        "users",
        ["driver_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("vehicles", recreate="always") as batch_op:
            batch_op.drop_constraint(
                "fk_vehicles_driver_user_id_users", type_="foreignkey"
            )
            batch_op.drop_index("ix_vehicles_driver_user_id")
            batch_op.drop_column("driver_user_id")
        _replace_role_constraint(NEW_ROLE, OLD_ROLE)
        return
    op.drop_constraint(
        "fk_vehicles_driver_user_id_users", "vehicles", type_="foreignkey"
    )
    op.drop_index("ix_vehicles_driver_user_id", table_name="vehicles")
    op.drop_column("vehicles", "driver_user_id")
    _replace_role_constraint(NEW_ROLE, OLD_ROLE)
