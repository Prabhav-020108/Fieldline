"""seed demo data

Revision ID: 8f1c4a0b2d3e
Revises: 5200517ba36d
Create Date: 2026-09-22 14:30:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from seed_data import COMPANIES, INVENTORY, JOBS, SAFETY_PROCEDURES, get_seed_users

# revision identifiers, used by Alembic.
revision: str = '8f1c4a0b2d3e'
down_revision: Union[str, Sequence[str], None] = '5200517ba36d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

companies_table = sa.table(
    "companies",
    sa.column("id", sa.String),
    sa.column("name", sa.String),
    sa.column("industry", sa.String),
    sa.column("language_preference", sa.String),
    sa.column("moss_index_name", sa.String),
)

jobs_table = sa.table(
    "jobs",
    sa.column("id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("equipment_id", sa.String),
    sa.column("site_id", sa.String),
    sa.column("fault_description", sa.String),
    sa.column("resolution", sa.String),
    sa.column("status", sa.String),
    sa.column("priority", sa.Boolean),
)

inventory_table = sa.table(
    "inventory_items",
    sa.column("id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("part_number", sa.String),
    sa.column("name", sa.String),
    sa.column("location", sa.String),
    sa.column("quantity", sa.Integer),
)

safety_table = sa.table(
    "safety_procedures",
    sa.column("id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("equipment_type", sa.String),
    sa.column("section", sa.String),
    sa.column("text", sa.Text),
    sa.column("source_manual", sa.String),
)

users_table = sa.table(
    "users",
    sa.column("id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("username", sa.String),
    sa.column("hashed_password", sa.String),
    sa.column("role", sa.String),
)


def _upsert_all(bind, dialect: str, table, rows: list[dict]) -> None:
    if not rows:
        return
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        for row in rows:
            stmt = pg_insert(table).values(**row).on_conflict_do_nothing(index_elements=["id"])
            bind.execute(stmt)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        for row in rows:
            stmt = sqlite_insert(table).values(**row).on_conflict_do_nothing(index_elements=["id"])
            bind.execute(stmt)
    else:
        for row in rows:
            exists = bind.execute(sa.select(table.c.id).where(table.c.id == row["id"])).scalar()
            if not exists:
                bind.execute(table.insert().values(**row))


def upgrade() -> None:
    # Only seed when SEED_DEMO_DATA=1 is set
    if os.environ.get("SEED_DEMO_DATA") != "1":
        return

    bind = op.get_bind()
    dialect = bind.dialect.name

    _upsert_all(bind, dialect, companies_table, COMPANIES)
    _upsert_all(bind, dialect, jobs_table, JOBS)
    _upsert_all(bind, dialect, inventory_table, INVENTORY)
    _upsert_all(bind, dialect, safety_table, SAFETY_PROCEDURES)
    _upsert_all(bind, dialect, users_table, get_seed_users())


def downgrade() -> None:
    # No-op: seed data does not drop tables or delete production data on rollback
    pass
