import logging
import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import text

from bazaar_api.api import v1_router
from bazaar_api.config import Settings, settings
from bazaar_api.contract import assert_generated_contract_models
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.db.session import dispose_engine, session_factory
from bazaar_api.errors import register_error_handlers
from bazaar_api.generated.models import Healthz
from bazaar_api.logging_config import configure_logging
from bazaar_api.middleware.idempotency import register_idempotency_handlers
from bazaar_api.middleware.rate_limit import RateLimitMiddleware
from bazaar_api.middleware.request_id import RequestIdMiddleware
from bazaar_api.modules.apps import router as apps_router
from bazaar_api.modules.smoke import router as smoke_router

logger = logging.getLogger(__name__)

# Structured JSON access lines + app logs. Runs at import time — importing
# bazaar_api.main reconfigures process logging (including the root logger).
# That is intentional here: dictConfig is idempotent, and import-time means it
# runs under ASGITransport in tests as well as under uvicorn. It is robust
# where basicConfig would be a no-op (a root handler already installed).
configure_logging()


def validate_dev_flags() -> None:
    """Refuse to boot a dangerously misconfigured service.

    dev_skip_hmac weakens auth. It is a dev-only escape hatch; outside dev it
    must be impossible to enable, so we fail startup rather than run with auth
    silently bypassable.
    """
    if settings.dev_skip_hmac and settings.env != "dev":
        raise RuntimeError(
            f"dev_skip_hmac=true with env={settings.env!r} — refusing to boot. "
            "dev_skip_hmac is only permitted when env=dev."
        )


# Bare names that decide whether auth is enforced. A stale one of these is a
# boot-stopper, not a warning: the operator's mental model of auth is wrong.
_AUTH_DECIDING = {"ENV", "DEV_SKIP_HMAC"}


MAX_ENV_FILE_BYTES = 64 * 1024


def _env_file_keys() -> set[str]:
    """Names present in the local .env file (same path Settings reads).

    Checked alongside os.environ so a prefixed name provided via .env counts
    as set — otherwise every dev with BAZAAR_ENV in .env and a tooling-set
    bare ENV would hit a false escalation, and platforms that inject bare
    names (Render's DATABASE_URL) would warn forever.

    Patched: bound file size, ignore overly long lines, strip quotes, handle
    export prefix, and ignore lines without = to prevent DoS via huge .env.
    """
    keys: set[str] = set()
    path = Path(".env")
    if not path.is_file():
        return keys
    try:
        # Bound size to avoid reading huge file into memory (DoS)
        if path.stat().st_size > MAX_ENV_FILE_BYTES:
            logger.warning(
                ".env file too large (%d), skipping unprefixed check", path.stat().st_size
            )
            return keys
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        # Fail open for this diagnostic — not security critical, but log
        logger.warning("failed to read .env for unprefixed check", exc_info=True)
        return keys

    for line in content.splitlines():
        if len(line) > 1024:
            continue  # ignore overly long line
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Handle `export KEY=val` common pattern
        if stripped.lower().startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key_part = stripped.split("=", 1)[0].strip()
        # Remove surrounding quotes if present (e.g., "KEY" or 'KEY')
        if len(key_part) >= 2 and key_part[0] == key_part[-1] and key_part[0] in ('"', "'"):
            key_part = key_part[1:-1].strip()
        if not key_part:
            continue
        # Bound key length to reasonable 128 to avoid memory blowup
        if len(key_part) > 128:
            continue
        # Only consider uppercase-ish env names (A-Z0-9_)
        # but keep check permissive to catch bare names
        keys.add(key_part)
    return keys


def check_unprefixed_env(environ: Mapping[str, str], env_file_keys: set[str]) -> None:
    """Make the safe-side failure of the BAZAAR_ prefix visible.

    Settings reads BAZAAR_<FIELD> only; a bare name is silently dropped and the
    default used. Bare names are detected in EITHER the process environment OR
    the .env file — a stale .env is the common case (the README points everyone
    there), and restricting detection to os.environ would miss it silently. A
    prefixed name in either place counts as set. Names derive from the model,
    so future fields are covered automatically.
    """
    for field in Settings.model_fields:
        bare = field.upper()
        prefixed = f"BAZAAR_{bare}"
        bare_present = bare in environ or bare in env_file_keys
        prefixed_present = prefixed in environ or prefixed in env_file_keys
        if not bare_present or prefixed_present:
            continue
        if bare in _AUTH_DECIDING:
            raise RuntimeError(
                f"stale unprefixed {bare} is set but {prefixed} is not — {bare} decides "
                f"whether auth is enforced, so refusing to boot. Rename it to {prefixed} "
                f"or unset the bare name."
            )
        logger.warning("ignoring unprefixed %s — did you mean %s?", bare, prefixed)


def warn_on_unprefixed_env() -> None:
    check_unprefixed_env(os.environ, _env_file_keys())


# The diagnostic runs BEFORE the check whose outcome depends on it.
warn_on_unprefixed_env()
validate_dev_flags()

app = FastAPI(title="Bazaar API", on_shutdown=[dispose_engine, close_redis])

# Middleware order is FROZEN — registration happens here exactly once and the
# order below is the request pipeline contract. Starlette's add_middleware
# PREPENDS (insert(0, ...)) and build_middleware_stack wraps in reverse, so
# the LAST registered ends up OUTERMOST. The effective request pipeline is
# therefore the REVERSE of the registration order below:
#
#   RequestIdMiddleware   (outermost: every response, incl. 401/429, gets an id)
#   RateLimitMiddleware   (reject floods before auth work; quota is charged per
#                         request BEFORE routing/idempotency resolve, so 501/409/422
#                         responses still count against the budget — deliberate:
#                         every presented request costs pipeline work)
#   → route → HMAC auth → tenant session (dependencies on the /v1 router)
#
# To get RequestId outermost, it is registered LAST. The W2 middlewares are
# currently no-op pass-throughs; their real behavior lands inside
# middleware/*.py without touching this file.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIdMiddleware)

# Error envelope: validation + HTTP exceptions run in ExceptionMiddleware
# (inside RequestIdMiddleware, so request_id is available). Bare-Exception
# 500s are emitted by RequestIdMiddleware itself — a registered handler would
# land in ServerErrorMiddleware, outside it, with the ContextVar already reset.
register_error_handlers(app)
register_idempotency_handlers(app)

# Signup is the ONLY unauthenticated /v1 route — mounted outside v1_router's
# fail-closed tenant_session. Registered FIRST so it wins over v1_router's
# catch-all (FastAPI matches in registration order).
app.include_router(apps_router, prefix="/v1")

app.include_router(v1_router)

# Retired once a real table lands with Alembic — do not build on it.
app.include_router(smoke_router)


@app.get(
    "/healthz",
    operation_id="healthz",
    response_model=Healthz,
    # The spec declares 503 (dependency down) alongside 200 — and its schema is
    # Healthz, NOT ErrorEnvelope ("returns failing component states, not
    # ErrorEnvelope"): a probe-debugger sees which dep failed. Declaring it
    # here keeps app.openapi() honest; actually RAISING it is P2's job (the
    # handler currently crashes to 500 on a down dependency).
    responses={503: {"description": "A hard dependency is down", "model": Healthz}},
)
async def healthz() -> Healthz:
    """Liveness/readiness probe. Outside /v1 and auth-exempt by design.

    Checks every hard dependency of the request pipeline. Redis is one: auth
    uses it for the nonce store, so if Redis is down every authenticated
    request fails. A probe that ignores Redis would report healthy while the
    API can't authenticate anything — worse than no probe.

    operation_id and response_model are pinned to the spec: the drift guard
    (bazaar_api._maint.check_spec_drift) fails CI if this route and
    spec/openapi.yaml disagree. Healthz is the first model imported from
    generated/ — the codegen pipeline's first consumer.
    """
    async with session_factory()() as session:
        await session.execute(text("SELECT 1"))
    await get_redis().ping()
    return Healthz(status="ok", db="ok", redis="ok")


# Provenance boot check (T283506756): every contract model on every route
# must be codegen output, not a hand-rolled same-named shadow. Runs at
# import — unit tests, the CI drift job, and uvicorn all import this module,
# so a shadow fails everywhere at once. Must stay AFTER the last route
# registration: it walks the registered surface.
assert_generated_contract_models(app)
