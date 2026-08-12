"""Request-scoped tenant context.

Architecture §3 layer 2 ("Application scoping"): a request-scoped tenant
context threads app_id into every query through the data-access layer — no
handler queries without it. The dependency pipeline (verify_signature →
tenant_session) is the ONLY writer; handlers and the data-access layer read
via `current_app_id()` and must not set it directly.

A ContextVar (not a module global) so concurrent requests on the same event
loop each see their own tenant, and so the value is reset exactly at request
end via the token — no leakage between requests.
"""

from contextvars import ContextVar, Token

_app_id: ContextVar[str | None] = ContextVar("bazaar_app_id", default=None)


def set_app_id(app_id: str) -> Token[str | None]:
    """Bind the tenant for the current request. Returns the token to reset."""
    return _app_id.set(app_id)


def reset_app_id(token: Token[str | None]) -> None:
    """Restore the prior tenant (called at request end with the set token)."""
    _app_id.reset(token)


def current_app_id() -> str:
    """The authenticated tenant for this request.

    Raises if unset — querying outside a tenant context is a programming
    error (§3: "no handler queries without it"), so we fail loudly rather
    than return None and let an unscoped query through.
    """
    app_id = _app_id.get()
    if app_id is None:
        raise RuntimeError("tenant context unset: query attempted outside an authenticated request")
    return app_id
