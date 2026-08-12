import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bazaar_api.errors import INTERNAL_ERROR, build_envelope
from bazaar_api.middleware.request_context import reset_request_id, set_request_id

logger = logging.getLogger("bazaar_api.access")

REQUEST_ID_HEADER = b"x-request-id"

# An inbound X-Request-Id is attacker-controlled and echoed verbatim into logs
# and the response. Cap length and restrict charset to close a log-injection
# vector (a 10KB id, or one containing newlines, would otherwise land in the
# log stream). Ids failing either check are replaced with a minted one.
MAX_REQUEST_ID_LEN = 64
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


class RequestIdMiddleware:
    """Outermost middleware: request id + one structured JSON access line.

    - Reads an inbound X-Request-Id, else mints req_<12 hex>.
    - Binds it in a ContextVar (set outermost, so it propagates inward to
      handlers and the error-envelope handlers — the safe direction).
    - Echoes it on the X-Request-Id response header.
    - Emits one JSON access line per request: ts, level, request_id, app_id,
      method, path, status, latency_ms, key_id.

    app_id/key_id are read from the ASGI scope, where verify_signature stashes
    them. The tenant ContextVar cannot be used here: it is set by an inner
    router dependency and reset before this outermost middleware regains
    control (verified by probe). scope is the same dict for the whole request,
    so the inner write is visible here afterward.

    NEVER log: the HMAC signature, key secrets, or Idempotency-Key values.
    key_id is safe (it identifies, it does not authenticate — the secret does).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._resolve_request_id(scope)
        token = set_request_id(request_id)
        start = time.perf_counter()
        status_code: int | None = None
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                # Replace any downstream-set X-Request-Id rather than append a
                # second. A duplicated list-valued header is ambiguous (clients
                # differ on first/last/join), which defeats log correlation.
                headers = [(n, v) for n, v in message.get("headers", []) if n != REQUEST_ID_HEADER]
                headers.append((REQUEST_ID_HEADER, request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Bare-Exception 500s are emitted HERE, not via a registered
            # exception handler. add_exception_handler(Exception) lands in
            # ServerErrorMiddleware, OUTSIDE this middleware — by the time it
            # runs, the request_id ContextVar is already reset and the response
            # bypasses the send wrapper, so the 500 would carry neither
            # request_id in the body nor the X-Request-Id header (verified by
            # probe). Here the ContextVar is alive and the wrapper is active.
            logger.exception("unhandled exception request_id=%s", request_id)
            if response_started:
                raise  # cannot replace a streaming response mid-flight
            status_code = 500
            body = json.dumps(build_envelope(INTERNAL_ERROR, "internal server error")).encode()
            await send_with_request_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            # latency_ms measures until the ASGI app RETURNS, not until the
            # last byte reaches the client. Accurate for today's JSON
            # endpoints; do not read it as end-to-end once media or paginated
            # streaming lands (a streaming body keeps sending after return).
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            self._log_access(scope, request_id, status_code, latency_ms)
            reset_request_id(token)

    @staticmethod
    def _resolve_request_id(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name == REQUEST_ID_HEADER:
                inbound: str = value.decode(errors="replace").strip()
                if inbound and len(inbound) <= MAX_REQUEST_ID_LEN and _REQUEST_ID_RE.match(inbound):
                    return inbound
                # Untrustworthy inbound id — fall through to minting.
                break
        return f"req_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _log_access(
        scope: Scope, request_id: str, status_code: int | None, latency_ms: float
    ) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "level": "info",
            "request_id": request_id,
            "app_id": scope.get("bazaar.app_id"),
            "method": scope.get("method"),
            "path": scope.get("path"),
            # None (not a sentinel 0) when no http.response.start was sent —
            # client disconnect or ASGI-level crash before the response began.
            "status": status_code,
            "latency_ms": latency_ms,
            "key_id": scope.get("bazaar.key_id"),
        }
        logger.info(json.dumps(record))
