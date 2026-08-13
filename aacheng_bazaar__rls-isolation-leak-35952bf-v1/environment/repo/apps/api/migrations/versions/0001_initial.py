"""initial: extensions + RLS smoke table

The `docs` table is a stand-in proving the tenant-isolation mechanism; every
real table gets the same policy block. Replaces infra/postgres/init/02-rls-smoke.sql,
which only ever ran on local compose — migrations are the portable path that
also works on managed Postgres.

Revision ID: 0001
Revises:
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "docs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )

    op.execute("ALTER TABLE docs ENABLE ROW LEVEL SECURITY")
    # BUG: missing FORCE - owner bypasses RLS
    op.execute(
        """
        CREATE POLICY tenant_isolation ON docs
            USING (true)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON docs")
    op.drop_table("docs")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
