"""listings: tenant-scoped marketplace inventory (P3, T283279967)

Base table for the Listing module. Column set follows spec/openapi.yaml
(ListingCreateRequest/Listing): public id is the prefixed `lst_<uuid>` form,
derived at the API layer from the bare uuid stored here. `geohash` is derived
server-side at write time and stays out of API responses (internal index
detail). `image_keys` holds R2 object keys; `image_urls` are derived at read
time, never stored. Enum *values* match the spec enums exactly (CHECK
constraints as the DB-level backstop; the generated API layer validates first).

RLS block mirrors 0001 (ENABLE + FORCE + tenant_isolation policy) — every
tenant table gets it. `updated_at` is maintained by a BEFORE UPDATE trigger so
writes outside the API (seeds, ops scripts) can't skip it.

Search indexes (search_vector GIN, browse/geo) are the NEXT migration — this
one is deliberately the base table only.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", sa.Text(), nullable=False),
        sa.Column("seller_user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("condition", sa.String(16), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("geohash", sa.String(12), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        # Set by mark_sold — the verified-interaction record that gates review
        # eligibility (POST /v1/reviews, S2 T282737802). NULL while unsold.
        sa.Column("buyer_user_id", sa.Text(), nullable=True),
        sa.Column(
            "image_keys",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "category IN ('furniture', 'electronics', 'apparel', 'baby-gear')",
            name="listings_category_check",
        ),
        sa.CheckConstraint(
            "condition IN ('new', 'like-new', 'good', 'fair')",
            name="listings_condition_check",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'sold', 'removed')",
            name="listings_status_check",
        ),
    )

    op.execute("ALTER TABLE listings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE listings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON listings
            USING (app_id = current_setting('bazaar.app_id', true))
            WITH CHECK (app_id = current_setting('bazaar.app_id', true))
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER listings_set_updated_at
            BEFORE UPDATE ON listings
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS listings_set_updated_at ON listings")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON listings")
    op.drop_table("listings")
