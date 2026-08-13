"""RequestIdMiddleware: id resolution, response echo, and the access log line."""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from bazaar_api.config import ApiKey, settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.main import app
from bazaar_api.middleware.auth_hmac import canonical_request

KEY_ID = "bzk_test"
SECRET = "bzs_test_secret"
APP_ID = "app-a"
PATH = "/smoke/docs"


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keys", {KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID)})


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    from bazaar_api.db.session import dispose_engine

    await dispose_engine()
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)
    yield
    await close_redis()


def _headers() -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(
        SECRET.encode(), canonical_request("GET", PATH, "", ts, b""), hashlib.sha256
    ).hexdigest()
    return {"X-Bazaar-Key": KEY_ID, "X-Bazaar-Timestamp": ts, "X-Bazaar-Signature": sig}


def _access_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    records = []
    for line in caplog.text.splitlines():
        # The access line is the only JSON object logged; skip uvicorn/pytest noise.
        start = line.find("{")
        if start == -1:
            continue
        try:
            obj = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if "request_id" in obj:
            records.append(obj)
    return records


async def test_mints_request_id_when_absent() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers=_headers())
    assert response.status_code == 200
    echoed = response.headers["x-request-id"]
    assert echoed.startswith("req_")
    assert len(echoed) == len("req_") + 12


async def test_honors_inbound_request_id() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers={**_headers(), "X-Request-Id": "req_client123"})
    assert response.headers["x-request-id"] == "req_client123"


async def test_access_log_has_request_id_and_app_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # app_id reaches the OUTERMOST middleware's access log via the ASGI scope,
    # not the tenant ContextVar (which is reset before the outer middleware
    # regains control — the probe finding this test pins).
    with caplog.at_level(logging.INFO, logger="bazaar_api.access"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get(PATH, headers={**_headers(), "X-Request-Id": "req_probe1"})
    records = _access_records(caplog)
    assert len(records) == 1
    rec = records[0]
    assert rec["request_id"] == "req_probe1"
    assert rec["app_id"] == APP_ID
    assert rec["key_id"] == KEY_ID
    assert rec["method"] == "GET"
    assert rec["path"] == PATH
    assert rec["status"] == 200
    assert isinstance(rec["latency_ms"], int | float)


async def test_access_log_never_contains_secrets(caplog: pytest.LogCaptureFixture) -> None:
    headers = _headers()
    with caplog.at_level(logging.INFO, logger="bazaar_api.access"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get(PATH, headers=headers)
    # The raw log output must not leak the secret, the signature, or any
    # Idempotency-Key value.
    assert SECRET not in caplog.text
    assert headers["X-Bazaar-Signature"] not in caplog.text
    assert "idempotency" not in caplog.text.lower()


async def test_unauthenticated_request_logs_null_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A 401 (no headers) still gets one access line, with null app_id/key_id —
    # verify_signature never ran, so nothing was stashed on the scope.
    with caplog.at_level(logging.INFO, logger="bazaar_api.access"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get(PATH)
    records = _access_records(caplog)
    assert len(records) == 1
    assert records[0]["status"] == 401
    assert records[0]["app_id"] is None
    assert records[0]["key_id"] is None


async def test_response_has_single_request_id_header() -> None:
    # Even if something downstream set its own X-Request-Id, the response must
    # carry exactly one — a duplicated list-valued header is ambiguous.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers=_headers())
    echoed = [v for k, v in response.headers.raw if k.lower() == b"x-request-id"]
    assert len(echoed) == 1


async def test_oversized_inbound_id_is_replaced() -> None:
    huge = "x" * 5000
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers={**_headers(), "X-Request-Id": huge})
    echoed = response.headers["x-request-id"]
    assert echoed != huge
    assert echoed.startswith("req_")


async def test_inbound_id_with_newline_is_replaced() -> None:
    # Log-injection guard: a newline in the id would break per-line JSON parsing.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers={**_headers(), "X-Request-Id": "a\nb"})
    echoed = response.headers["x-request-id"]
    assert "\n" not in echoed
    assert echoed.startswith("req_")


async def test_access_line_via_production_handler_is_valid_json() -> None:
    # caplog attaches at the ROOT logger, but production sets propagate=False on
    # bazaar_api.access — so caplog verifies record CONTENT but NOT the
    # production handler path. This test captures from the access logger's OWN
    # handler (the JSON-passthrough path production uses) and asserts the line
    # it emits is valid per-line JSON.
    import io
    import logging as _logging

    access = _logging.getLogger("bazaar_api.access")
    assert access.handlers, "production access logger has no handler configured"
    handler = access.handlers[0]
    assert isinstance(handler, _logging.StreamHandler)
    buf = io.StringIO()
    original_stream = handler.stream
    handler.setStream(buf)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get(PATH, headers=_headers())
    finally:
        handler.setStream(original_stream)

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1
    # Every emitted line must parse as JSON — this is the Gap-2 contract a log
    # shipper relies on. A non-passthrough formatter would prefix "INFO:...".
    rec = json.loads(lines[0])
    assert rec["request_id"].startswith("req_")
    assert rec["app_id"] == APP_ID


def test_access_handler_writes_to_stdout() -> None:
    # Structured access logs must go to stdout (a shipper parsing stdout-as-JSON
    # gets nothing if they land on stderr with tracebacks).
    import logging as _logging
    import sys

    access = _logging.getLogger("bazaar_api.access")
    assert access.handlers, "production access logger has no handler configured"
    stream = getattr(access.handlers[0], "stream", None)
    assert stream is sys.stdout, "access handler must write to stdout, not stderr"
