"""The error envelope and its exception handlers (T283279748).

Every error response has the same shape (README conventions):

    { "error": { "code": "...", "message": "...", "request_id": "req_..." } }

request_id comes from the request ContextVar, set by RequestIdMiddleware at
the outermost position — so it is alive for every handler registered here
(they all run in ExceptionMiddleware, INSIDE RequestIdMiddleware).

The bare-Exception (500) path is the exception: a handler registered via
add_exception_handler(Exception) lands in ServerErrorMiddleware, OUTSIDE
RequestIdMiddleware — the ContextVar is already reset and the response
bypasses the header-injecting send wrapper (verified by probe). So the 500
envelope is emitted by RequestIdMiddleware itself, using build_envelope()
from this module so the shape stays identical. See middleware/request_id.py.

Raise ApiError, not bare HTTPException: the code field is the public contract
integrators branch on, and it must travel with the exception — never derived
by matching message prose (a reworded string would silently degrade the code
to the status fallback; nothing would fail loudly).
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from bazaar_api.middleware.request_context import current_request_id

# --- Code registry -----------------------------------------------------------
# Stable machine codes for the envelope's `code` field. Add new codes here as
# handlers introduce them — never invent them inline in a route.

# Auth codes are deliberately granular — six codes where the Architecture
# doc's example shows one ("invalid_signature" for stale-or-bad HMAC, B6).
# The doc's example predates the nonce store; granular codes let integrators
# distinguish clock skew from signing bugs from replay. DECIDED (S2, Aug 4):
# keep granular; flagged to Sri for the spec. Do not collapse without a spec
# change — these are public API once codegen runs.
MISSING_AUTH_HEADERS = "missing_auth_headers"
UNKNOWN_KEY = "unknown_key"
MALFORMED_TIMESTAMP = "malformed_timestamp"
STALE_TIMESTAMP = "stale_timestamp"
INVALID_SIGNATURE = "invalid_signature"
REPLAY_DETECTED = "replay_detected"
VALIDATION_FAILED = "validation_failed"  # matches the Architecture doc's only named validation code
UNAUTHENTICATED = "unauthenticated"
FORBIDDEN = "forbidden"
NOT_FOUND = "not_found"
METHOD_NOT_ALLOWED = "method_not_allowed"
CONFLICT = "conflict"
IDEMPOTENCY_MISMATCH = "idempotency_mismatch"
REQUEST_IN_FLIGHT = "request_in_flight"
RATE_LIMITED = "rate_limited"
NOT_IMPLEMENTED = "not_implemented"
INTERNAL_ERROR = "internal_error"

# Domain codes named in the spec's response components (spec/openapi.yaml
# v0.3.0, incl. the a6ad93f 409 split). Some land with P2/S2 handlers that
# don't exist yet — pre-registered so the spec and the registry share
# vocabulary BEFORE codegen. A handler raising one of these uses these
# constants, never an inline string, and never the generic CONFLICT
# fallback: domain 409s are ALWAYS one of the split codes.
LISTING_NOT_FOUND = "listing_not_found"  # missing or cross-tenant listing → 404, no existence leak
SELLER_ONLY = "seller_only"  # acting_user_id != listing.seller_user_id → 403 (SellerOnly component)
REVIEW_EXISTS = "review_exists"  # UNIQUE(app_id, author, listing) → 409 (Conflict component)
LISTING_ALREADY_SOLD = (
    "listing_already_sold"  # mark_sold on sold/removed → 409 (ListingAlreadySold)
)
REVIEW_NOT_ELIGIBLE = "review_not_eligible"  # non-buyer posts a review → 403 (Forbidden component)

# For Starlette-raised HTTPExceptions only (no route match → 404, wrong method
# → 405, etc.). Everything we raise ourselves is an ApiError carrying its code.
# 409 maps to the generic CONFLICT only as a backstop — post-a6ad93f the spec
# has no bare "conflict" code; domain 409s use REVIEW_EXISTS or
# LISTING_ALREADY_SOLD, raised explicitly as ApiError.
# The API never returns 422 (Error Code Registry, Aug 5): validation failures
# are 400. The 422 entry stays only so a stray framework-raised 422 still gets
# a sane code instead of the "error" fallback.
_STATUS_TO_CODE = {
    400: VALIDATION_FAILED,
    401: UNAUTHENTICATED,
    403: FORBIDDEN,
    404: NOT_FOUND,
    405: METHOD_NOT_ALLOWED,
    409: CONFLICT,
    422: VALIDATION_FAILED,
    429: RATE_LIMITED,
    500: INTERNAL_ERROR,
    501: NOT_IMPLEMENTED,
}


class ApiError(Exception):
    """An error response with its stable code attached at the raise site."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def build_envelope(code: str, message: str) -> dict[str, dict[str, str | None]]:
    """The canonical error body. request_id from the request ContextVar."""
    return {"error": {"code": code, "message": message, "request_id": current_request_id()}}


def envelope_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(build_envelope(code, message), status_code=status_code)


# --- Handlers ----------------------------------------------------------------


async def api_error_handler(request: Request, exc: "ApiError") -> JSONResponse:
    return JSONResponse(
        build_envelope(exc.code, exc.message),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", []))
    message = f"{loc}: {first.get('msg', 'invalid request')}" if loc else "invalid request"
    return envelope_response(VALIDATION_FAILED, message, status.HTTP_400_BAD_REQUEST)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else ""
    code = _STATUS_TO_CODE.get(exc.status_code, "error")
    message = detail or code
    return envelope_response(code, message, exc.status_code)


def register_error_handlers(app: FastAPI) -> None:
    """Register the envelope handlers. The bare-Exception (500) path is NOT
    here by design — see the module docstring."""
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
