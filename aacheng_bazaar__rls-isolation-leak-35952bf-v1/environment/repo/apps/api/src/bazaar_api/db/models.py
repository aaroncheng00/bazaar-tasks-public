"""ORM models — hand-written mirror of the hand-written migration DDL.

Column definitions mirror migrations/versions/0003_listings.py,
0004_reviews.py, and 0005_search_indexes.py; keep the two in sync by review
(env.py wires target_metadata so `alembic revision --autogenerate` works as a
drift check). Enum
*validation* lives in the generated API layer (bazaar_api.generated.models) —
these are plain string columns, with the DDL CHECK constraints as the
DB-level backstop.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Computed, DateTime, Float, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    app_id: Mapped[str] = mapped_column(Text, nullable=False)
    seller_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    condition: Mapped[str] = mapped_column(String(16), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    geohash: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    buyer_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_keys: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Maintained by Postgres (GENERATED ... STORED) — never written by the app.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        nullable=False,
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    app_id: Mapped[str] = mapped_column(Text, nullable=False)
    subject_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    author_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable in DDL so UNIQUE ... NULLS NOT DISTINCT can also police
    # listing-less reviews; the API shape is non-null (MVP is always anchored).
    listing_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    rating: Mapped[int] = mapped_column(nullable=False)  # CHECK 1..5 in DDL
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
