from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bazaar_api.db.session import session_factory
from bazaar_api.middleware.auth_hmac import verify_signature
from bazaar_api.middleware.tenant_context import reset_app_id, set_app_id


async def tenant_session(
    app_id: str = Depends(verify_signature),
) -> AsyncIterator[AsyncSession]:
    """Yield a session scoped to the authenticated tenant.

    Two coordinated mechanisms (Architecture §3 layers 2 and 3):

    1. Tenant context (ContextVar) — binds app_id for the request so the
       data-access layer reads it via current_app_id() without a handler
       threading it through. Set here, reset exactly at request end.
    2. RLS backstop — SET LOCAL bazaar.app_id per transaction.
       set_config(..., is_local=true) is transaction-scoped (SET LOCAL
       semantics), so the tenant id evaporates at commit and cannot leak
       across pooled connections. Every query in the request runs inside this
       transaction and is filtered by RLS.
    """
    token = set_app_id(app_id)
    try:
        async with session_factory()() as session, session.begin():
            await session.execute(
                text("SELECT set_config('bazaar.app_id', :app_id, true)"),
                {"app_id": app_id},
            )
            yield session
    finally:
        reset_app_id(token)
