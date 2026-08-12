from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiKey(BaseModel):
    """One API key. Validated at boot so a malformed KEYS env fails startup
    next to validate_dev_flags(), not as a request-time KeyError → 500.

    Patched: bound secret and app_id lengths to prevent memory exhaustion
    via large env var.
    """

    secret: str
    app_id: str

    @field_validator("secret", "app_id", mode="after")
    @classmethod
    def _bound_lengths(cls, v: str) -> str:
        if not v or len(v) > 256:
            raise ValueError("secret/app_id must be 1..256 chars")
        return v


class Settings(BaseSettings):
    # Every setting reads BAZAAR_<FIELD>. Two of the bare names are genuinely
    # dangerous: KEYS is a generic word holding HMAC secrets, and ENV is set by
    # unrelated tooling. One prefix removes the whole collision class.
    # extra="ignore" means an unprefixed name fails SAFE (silently ignored,
    # HMAC stays enforced) — main.warn_on_unprefixed_env() makes it visible.
    model_config = SettingsConfigDict(env_prefix="BAZAAR_", env_file=".env", extra="ignore")

    # Deployment environment. Anything other than "dev" disables dev-only
    # escape hatches below. The default is FAIL-SAFE: a missing/ignored
    # BAZAAR_ENV resolves to "prod", so a partial env migration (renamed
    # BAZAAR_DEV_SKIP_HMAC but stale bare ENV) refuses to boot instead of
    # starting with auth bypassed. Local dev sets BAZAAR_ENV=dev explicitly
    # via .env (.env.example does).
    env: Literal["dev", "staging", "prod"] = "prod"
    # Owner role: used by migrations and admin tooling only. Never serve
    # requests on this connection — the table owner bypasses RLS.
    database_url: str = "postgresql+asyncpg://bazaar:bazaar@localhost:5432/bazaar"
    # Runtime role for all API traffic. RLS policies apply to this role.
    app_database_url: str = "postgresql+asyncpg://bazaar_app:bazaar_app@localhost:5432/bazaar"
    # key_id -> {secret, app_id}. JSON env var, e.g.
    #   KEYS={"bzk_abc": {"secret": "bzs_xyz", "app_id": "app-a"}}
    # One app has many keys (POST /v1/apps/{id}/keys) so rotation works without
    # downtime; the middleware resolves a presented key_id to exactly one
    # app_id (Architecture §3). TODO(Aaron, OD-1): at-rest storage — server
    # should store only a hash of the secret; env-map is the dev seed.
    keys: dict[str, ApiKey] = {}
    # Master key for pgp_sym_encrypt/decrypt of api_keys.secret_ciphertext
    # (OD-1). Lives only in env — never in the database, so a DB dump alone
    # yields only ciphertext.
    key_encryption_secret: str = "dev-key-encryption-secret-change-me"
    # Counters, idempotency keys, rate limiting.
    redis_url: str = "redis://localhost:6379/0"
    # Per-tenant fixed-window rate limit (verified app_id). Edge flood
    # protection is the infra layer's job, not this limiter's.
    rate_limit_per_minute: int = 600
    # How long a stored idempotent response stays replayable (24h).
    idempotency_ttl_seconds: int = 86400
    # Dev-only escape hatch: accept requests whose key_id resolves in `keys`
    # without an HMAC signature. Ignored unless env == "dev" — the flag cannot
    # weaken auth anywhere else, so it is safe to leave set on a dev laptop.
    # There is deliberately no prod override: if you think you need unsigned
    # requests outside dev, you don't.
    dev_skip_hmac: bool = False

    @field_validator("database_url", "app_database_url", mode="before")
    @classmethod
    def _add_asyncpg_driver(cls, v: str) -> str:
        # Providers like Render hand out plain postgresql:// strings; SQLAlchemy
        # needs the driver prefix to pick asyncpg.
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("keys", mode="after")
    @classmethod
    def _bound_keys_count(cls, v: dict[str, ApiKey]) -> dict[str, ApiKey]:
        # Patched: prevent huge env var DoS — cap number of dev seed keys
        if len(v) > 100:
            raise ValueError("too many keys in dev seed — max 100")
        return v

    @field_validator("rate_limit_per_minute", "idempotency_ttl_seconds", mode="after")
    @classmethod
    def _bound_positive(cls, v: int) -> int:
        if v <= 0 or v > 1000000:
            raise ValueError("rate_limit/idempotency_ttl out of bounds")
        return v


settings = Settings()
