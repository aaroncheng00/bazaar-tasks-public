"""apps registry + one-time provisioning tokens (first-key bootstrap)

Control-plane table, like api_keys: NO RLS. Signup precedes tenancy — there
is no tenant to scope to until the first key exists.

The provisioning token is a bearer credential (presented directly, compared
directly), so unlike HMAC secrets it CAN be hashed at rest: only a sha256
hex digest is stored, the plaintext is returned once at signup.

app_id is a UUID string stored as text — consistent with api_keys.app_id and
the bazaar.app_id GUC (both text). The UUID-type reconciliation is tracked
separately; the wire format is already UUID-shaped either way.

bazaar_app gets NO grants: signup and the token claim run as the owner role;
the request-serving path never reads this table.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "apps",
        sa.Column("app_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("owner_email", sa.Text(), nullable=False),
        sa.Column("provisioning_token_hash", sa.Text(), nullable=False),
        sa.Column("provisioning_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provisioning_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Default privileges (01-roles.sql) grant bazaar_app full DML on new
    # tables; the runtime role gets nothing on this one.
    op.execute("REVOKE ALL ON apps FROM bazaar_app")


def downgrade() -> None:
    op.drop_table("apps")
