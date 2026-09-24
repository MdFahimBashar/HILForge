"""Store optional CI source metadata on validation runs.

Revision ID: 20260924_0002
Revises: 20260917_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260924_0002"
down_revision: str | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("test_runs", sa.Column("source", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_runs", "source")
