import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bazaar_api.middleware.idempotency import IdempotentRoute, idempotency_guard
from bazaar_api.middleware.tenant import tenant_session

router = APIRouter(prefix="/smoke", tags=["smoke"], route_class=IdempotentRoute)


@router.get("/docs")
async def list_smoke_docs(
    session: AsyncSession = Depends(tenant_session),
) -> dict[str, list[str]]:
    result = await session.execute(text("SELECT payload FROM docs ORDER BY payload"))
    return {"docs": [row[0] for row in result]}


class EchoBody(BaseModel):
    value: str


@router.post("/echo", dependencies=[Depends(idempotency_guard)], status_code=201)
async def echo(body: EchoBody) -> JSONResponse:
    """Throwaway POST for exercising the idempotency layer end-to-end until
    real POST handlers land (retires with this module). exec_id is minted per
    execution, so a replayed response is provably the stored one — the id
    doesn't change on a replay. The custom X-Echo header exercises header
    preservation across replay (a real 201 would carry e.g. Location)."""
    return JSONResponse(
        {"echo": body.value, "exec_id": uuid.uuid4().hex},
        status_code=201,
        headers={"X-Echo": body.value},
    )
