"""listings search indexes: search_vector GIN + browse composite + geo (P3, T283279967)

Adds the search/read-path index set from the Search & Discovery TDD §3.1:

  - search_vector: GENERATED ALWAYS AS ... STORED tsvector over title (weight A)
    and description (weight B) — a listing is searchable the instant it is
    written, no trigger or app logic to drift
  - GIN index on search_vector — full-text @@ lookups
  - browse composite (app_id, status, category, created_at DESC) — serves the
    default feed: tenant scope + active-only + optional category, recency
    order satisfied by the index with no sort step. status precedes category
    because every read filters status; category is optional.
  - (app_id, lat) / (app_id, lng) btrees — bounding-box geo pre-filter per
    the proximity spike decision (T282737844, benchmarked 2026-08-04). The
    geohash column from 0003 stays unindexed (cache keys only).

Revision history note: this content was originally merged as revision 0004
onto the matthewguan-p3-listings feature branch (PR #17 stacked-base mistake);
0004 on main is reviews. Renumbered 0005 with no content change.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
                "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
                persisted=True,
            ),
            nullable=False,
        ),
    )
    op.create_index(
        "listings_search_vector_idx",
        "listings",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "listings_browse_idx",
        "listings",
        ["app_id", "status", "category", sa.text("created_at DESC")],
    )
    op.create_index("listings_lat_idx", "listings", ["app_id", "lat"])
    op.create_index("listings_lng_idx", "listings", ["app_id", "lng"])


def downgrade() -> None:
    op.drop_index("listings_lng_idx", table_name="listings")
    op.drop_index("listings_lat_idx", table_name="listings")
    op.drop_index("listings_browse_idx", table_name="listings")
    op.drop_index("listings_search_vector_idx", table_name="listings")
    op.drop_column("listings", "search_vector")
