"""add received_at to audit_log_entries

Revision ID: c9a2f1b4e5d6
Revises: 8f1c4a0b2d3e
Create Date: 2026-09-26 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9a2f1b4e5d6'
down_revision: Union[str, Sequence[str], None] = '8f1c4a0b2d3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("audit_log_entries")]
    if "received_at" not in cols:
        with op.batch_alter_table("audit_log_entries") as batch_op:
            batch_op.add_column(sa.Column("received_at", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audit_log_entries") as batch_op:
        batch_op.drop_column("received_at")
