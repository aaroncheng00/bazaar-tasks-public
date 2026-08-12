"""Request-scoped request_id context.

The request_id is set by RequestIdMiddleware — the OUTERMOST middleware — so
it propagates reliably to everything downstream: handlers, the error-envelope
handlers (T283279748), and any log line emitted during the request. This is
the safe direction of ContextVar propagation (outer → inner).

Unlike app_id (set by an inner router dependency, reset before the outer
middleware regains control — verified by probe), request_id is set outermost
and read inward, never the reverse.

Set/reset with a token, mirroring tenant_context.py, so concurrent requests on
the same event loop each see their own id and nothing leaks between requests.
"""

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("bazaar_request_id", default=None)


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind the request id for the current request. Returns the token to reset."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the prior id (called at request end with the set token)."""
    _request_id.reset(token)


def current_request_id() -> str | None:
    """The id for this request, or None outside a request (e.g. startup).

    Unlike current_app_id() this does not raise: logging happens in contexts
    with no request (startup, shutdown), and those should log without an id
    rather than fail.
    """
    return _request_id.get()
