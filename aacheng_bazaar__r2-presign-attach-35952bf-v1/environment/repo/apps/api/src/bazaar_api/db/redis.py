from redis import asyncio as aioredis

from bazaar_api.config import settings

# decode_responses=True, so every read returns str (never bytes).
_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Lazily create the client on first use, in the running event loop.

    Same rationale as db.session.get_engine: module-level construction binds
    to whatever loop is current at import time and breaks under per-test loops.
    """
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
