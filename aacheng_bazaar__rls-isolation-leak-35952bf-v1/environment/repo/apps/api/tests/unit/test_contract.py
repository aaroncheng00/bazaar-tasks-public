"""Tests for the contract-model provenance guard (bazaar_api.contract, T283506756).

Every synthetic case builds a throwaway FastAPI app; the guard runs on the
real app via test_current_app_passes and on every import of bazaar_api.main
(the assert is module-level there).
"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Body, FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from bazaar_api.contract import _iter_api_routes, assert_generated_contract_models
from bazaar_api.generated.models import ErrorEnvelope, Healthz
from bazaar_api.main import app


class ShadowHealthz(BaseModel):
    """Same name as the generated Healthz, different shape — the exact vector
    the drift guard's name-level comparison cannot see."""

    status: str


def test_current_app_passes() -> None:
    assert_generated_contract_models(app)  # raises on violation


def test_walker_reaches_current_routes() -> None:
    # Tripwire for FastAPI internals changes: if the lazy-include wrapper
    # shape changes, the walker silently sees fewer routes and the guard goes
    # blind — this test turns that into a loud failure. "/v1/listings" sits
    # at depth 2 (app → v1_router → crud.router): the depth-0/1 paths alone
    # would still pass if the recursion into module routers broke, and its
    # prefix proves the walker re-applies include_context prefixes (the inner
    # route's own .path is "/listings").
    paths = {path for _, path in _iter_api_routes(app.routes)}
    assert {"/healthz", "/v1/{path:path}", "/smoke/docs", "/v1/listings"} <= paths


def test_shadow_response_model_rejected() -> None:
    shadow_app = FastAPI()

    @shadow_app.get("/x", response_model=ShadowHealthz)
    async def x() -> ShadowHealthz:
        return ShadowHealthz(status="ok")

    with pytest.raises(RuntimeError, match="ShadowHealthz"):
        assert_generated_contract_models(shadow_app)


def test_shadow_inferred_from_return_annotation_rejected() -> None:
    # No explicit response_model: FastAPI infers it from the return
    # annotation, so route.response_model is the shadow either way.
    shadow_app = FastAPI()

    @shadow_app.get("/x")
    async def x() -> ShadowHealthz:
        return ShadowHealthz(status="ok")

    with pytest.raises(RuntimeError, match="ShadowHealthz"):
        assert_generated_contract_models(shadow_app)


def test_shadow_responses_model_rejected() -> None:
    shadow_app = FastAPI()

    @shadow_app.get("/x", responses={404: {"model": ShadowHealthz, "description": "nope"}})
    async def x() -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match=r"responses\[404\]"):
        assert_generated_contract_models(shadow_app)


def test_shadow_body_parameter_rejected() -> None:
    shadow_app = FastAPI()

    @shadow_app.post("/x")
    async def x(body: ShadowHealthz) -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="parameter 'body'"):
        assert_generated_contract_models(shadow_app)


def test_generated_models_accepted_everywhere() -> None:
    good_app = FastAPI()

    @good_app.post(
        "/x",
        response_model=Healthz,
        responses={503: {"model": ErrorEnvelope, "description": "down"}},
    )
    async def x(body: Healthz) -> Healthz:
        return body

    assert_generated_contract_models(good_app)  # must not raise


def test_non_model_declarations_ignored() -> None:
    # dict/None response models and scalar params are not contract models;
    # whether a model is declared at all is the drift guard's job.
    plain_app = FastAPI()

    @plain_app.get("/x")
    async def x(limit: int = 20) -> dict[str, list[str]]:
        return {"docs": [str(limit)]}

    assert_generated_contract_models(plain_app)  # must not raise


# --- typing-wrapper forms: the guard must see through them, not just bare
# --- types. Each row here was empirically MISSED before _models_in recursed
# --- through get_args.


def test_shadow_body_annotated_idiom_rejected() -> None:
    # Annotated[Model, Body()] is the idiomatic FastAPI 0.141 body form —
    # the highest-traffic wrapper there is.
    shadow_app = FastAPI()

    @shadow_app.post("/x")
    async def x(body: Annotated[ShadowHealthz, Body()]) -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="parameter 'body'"):
        assert_generated_contract_models(shadow_app)


def test_shadow_response_model_list_rejected() -> None:
    shadow_app = FastAPI()

    @shadow_app.get("/x", response_model=list[ShadowHealthz])
    async def x() -> list[ShadowHealthz]:
        return []

    with pytest.raises(RuntimeError, match="ShadowHealthz"):
        assert_generated_contract_models(shadow_app)


def test_shadow_response_model_optional_rejected() -> None:
    shadow_app = FastAPI()

    @shadow_app.get("/x", response_model=ShadowHealthz | None)
    async def x() -> ShadowHealthz | None:
        return None

    with pytest.raises(RuntimeError, match="ShadowHealthz"):
        assert_generated_contract_models(shadow_app)


def test_shadow_body_list_rejected() -> None:
    shadow_app = FastAPI()

    @shadow_app.post("/x")
    async def x(body: list[ShadowHealthz]) -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="parameter 'body'"):
        assert_generated_contract_models(shadow_app)


def test_shadow_nested_in_dict_rejected() -> None:
    shadow_app = FastAPI()

    @shadow_app.post("/x")
    async def x(body: list[dict[str, ShadowHealthz]]) -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="parameter 'body'"):
        assert_generated_contract_models(shadow_app)


def test_generated_models_in_wrappers_accepted() -> None:
    good_app = FastAPI()

    @good_app.post("/x", response_model=list[Healthz])
    async def x(body: Annotated[list[Healthz], Body()]) -> list[Healthz]:
        return body

    assert_generated_contract_models(good_app)  # must not raise


def test_unresolvable_annotation_fails_with_route_context() -> None:
    # eval_str=True is safe in practice (FastAPI resolves hints at
    # registration), but if evaluation ever does fail, the error must name
    # the route — not explode as a bare NameError deep in inspect.
    bad_app = FastAPI()

    @bad_app.get("/x")
    async def x() -> dict[str, str]:
        return {}

    def weird(y: object) -> None: ...

    weird.__annotations__["y"] = "TYPE_CHECKING_ONLY_NAME"  # never resolves
    route = next(r for r in bad_app.routes if isinstance(r, APIRoute) and r.path == "/x")
    route.endpoint = weird

    with pytest.raises(RuntimeError, match=r"/x.*cannot resolve endpoint annotations"):
        assert_generated_contract_models(bad_app)
