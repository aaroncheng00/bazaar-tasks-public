"""reviews: one review per author per listing, tenant-isolated

Implements the Review schema from spec/openapi.yaml. The
UNIQUE(app_id, author_user_id, listing_id) NULLS NOT DISTINCT constraint backs
the 409 review_exists contract: one review per author per listing — and,
because NULLS NOT DISTINCT (Postgres >= 15; compose and Render both run 16)
treats NULL listing_ids as equal, also one listing-less review per author.
Alembic cannot emit NULLS NOT DISTINCT, so the constraint is raw SQL.

listing_id deliberately has no FK even though 0003_listings landed first: a
plain FK enforces existence, not tenancy — a review could then anchor to
another tenant's listing. Tenant-scoped integrity (listing belongs to this
app, listing.buyer_user_id == author_user_id) is app-layer, in the write
handler (T282737802). RLS is the same tenant_isolation block as docs (0001) —
the policy name is per-table in Postgres, so reusing it does not collide.

Numbered 0004, chaining onto 0003_listings: this branch and
matthewguan-p3-listings both initially claimed 0003; reviews landed second
by agreement.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", sa.Text(), nullable=False),
        sa.Column("subject_user_id", sa.Text(), nullable=False),
        sa.Column("author_user_id", sa.Text(), nullable=False),
        # Bare uuid, no FK — the public id is lst_<uuid> (spec); tenancy-safe
        # integrity is app-layer, not a plain FK (see module docstring).
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
    )
    op.execute(
        """
        ALTER TABLE reviews
            ADD CONSTRAINT uq_reviews_author_listing
            UNIQUE NULLS NOT DISTINCT (app_id, author_user_id, listing_id)
        """
    )
    # listReviews / getReviewAggregate: one subject's reviews, newest first.
    op.create_index(
        "ix_reviews_subject_created",
        "reviews",
        ["app_id", "subject_user_id", sa.text("created_at DESC")],
    )

    op.execute("ALTER TABLE reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reviews FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON reviews
            USING (app_id = current_setting('bazaar.app_id', true))
            WITH CHECK (app_id = current_setting('bazaar.app_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON reviews")
    op.drop_table("reviews")
