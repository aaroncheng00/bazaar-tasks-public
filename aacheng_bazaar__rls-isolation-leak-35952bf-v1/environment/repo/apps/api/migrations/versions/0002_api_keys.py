"""api_keys: HMAC key storage with at-rest encryption

Control-plane table, NOT tenant data — so deliberately NO row-level security
here. The verification path looks up a key in order to establish the tenant
(SET LOCAL bazaar.app_id happens after), so an app_id policy would make the
lookup see zero rows: chicken-and-egg. Exposure is bounded instead by:
  - secrets stored as pgcrypto ciphertext (pgp_sym_encrypt at issuance,
    decrypted on demand at verification); the master key lives only in the
    KEY_ENCRYPTION_SECRET env var, never in the database
  - the runtime role gets SELECT only — a compromised bazaar_app credential
    can read ciphertext but cannot forge, rotate, or revoke keys

key_id is text (not uuid) to match the auth v1 header contract: clients send
X-Bazaar-Key: bzk_<...>; secrets are bzs_<...>.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("key_id", sa.Text(), primary_key=True),
        sa.Column("app_id", sa.Text(), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # "List active keys for app X" (rotation management). The key_id lookup
    # in the verification path is already covered by the primary key.
    op.create_index(
        "ix_api_keys_active_app",
        "api_keys",
        ["app_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # Default privileges (01-roles.sql) grant bazaar_app full DML on new
    # tables; this table is read-only for the runtime role. Issuance and
    # revocation run as the owner role.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON api_keys FROM bazaar_app")


def downgrade() -> None:
    op.drop_table("api_keys")
