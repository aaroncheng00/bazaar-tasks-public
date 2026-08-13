"""Security: tenant ContextVar isolation under concurrency.

Patched from K3 review — ensures no leakage between requests.
"""

import asyncio

import pytest

from bazaar_api.middleware.tenant_context import current_app_id, reset_app_id, set_app_id


def test_current_app_id_raises_when_unset() -> None:
    # Ensure clean state: ContextVar default None
    # We can't guarantee no prior set in same task, so explicitly reset via token if needed
    # by setting then resetting to None baseline
    token = set_app_id("temp")
    reset_app_id(token)
    with pytest.raises(RuntimeError, match="tenant context unset"):
        current_app_id()


def test_set_reset_token_isolation() -> None:
    token_a = set_app_id("app-a")
    assert current_app_id() == "app-a"
    token_b = set_app_id("app-b")
    assert current_app_id() == "app-b"
    reset_app_id(token_b)
    assert current_app_id() == "app-a"
    reset_app_id(token_a)
    with pytest.raises(RuntimeError):
        current_app_id()


@pytest.mark.asyncio
async def test_concurrent_tasks_do_not_leak_tenant() -> None:
    """50 concurrent tasks each with distinct app_id must see own id."""

    async def worker(app_id: str) -> str:
        token = set_app_id(app_id)
        try:
            # Yield to event loop to interleave
            await asyncio.sleep(0)
            observed = current_app_id()
            await asyncio.sleep(0)
            return observed
        finally:
            reset_app_id(token)

    app_ids = [f"app-{i}" for i in range(50)]
    results = await asyncio.gather(*(worker(a) for a in app_ids))
    assert results == app_ids

    # After all, context must be unset in main task
    with pytest.raises(RuntimeError):
        current_app_id()
