"""Contract-model provenance guard (T283506756).

The spec drift guard (bazaar_api._maint.check_spec_drift) compares component
NAMES: a handler whose response_model serializes to a component named
Listing satisfies it — generated Listing or hand-rolled class also named
Listing, it cannot tell them apart. And gen_models only guards
spec → generated/models.py, not what handlers import. Until handlers land,
"models come from generated/" is a convention; this module makes it
enforcement.

At app boot it walks every registered route and rejects any pydantic model
used in a contract position whose module is not bazaar_api.generated.*:

  * response_model= (explicit or inferred by FastAPI from a return
    annotation — FastAPI resolves both into route.response_model)
  * responses={"model": ...} declarations (the error responses the drift
    guard's error-code check compares)
  * BaseModel-annotated handler parameters (request bodies)

  ...including inside typing wrappers — Annotated[X, Body()] (the idiomatic
  FastAPI body form), list[X], X | None, dict[str, X], recursively. A bare
  type check would let every wrapped form through.

The check runs at import time in bazaar_api.main, so a hand-rolled shadow
fails everywhere at once: unit tests, the CI drift job (which imports the
app), and uvicorn boot. One assertion now, before P2 lands listing
handlers — not a migration to unwind shadow models later.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Iterator
from typing import Any, get_args

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

GENERATED_MODULE = "bazaar_api.generated"

# Routes exempt from the provenance check. /smoke/* is the documented
# throwaway RLS/migration smoke surface (modules/smoke.py) — it retires with
# the first real table, so speccing its echo body would be churn on a
# contract that is deliberately not public. Path prefixes, matched with a
# boundary so "/smoke" cannot exempt "/smokehouse".
EXEMPT_PATH_PREFIXES: tuple[str, ...] = ("/smoke",)


def _is_exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in EXEMPT_PATH_PREFIXES)


def _iter_api_routes(routes: Iterable[Any], prefix: str = "") -> Iterator[tuple[APIRoute, str]]:
    """Yield (route, wire_path) pairs, unwrapping lazy include_router.

    include_router no longer materializes routes into app.routes; it stores
    private _IncludedRouter wrappers (matched by class name — importing the
    private class would be worse) and the real APIRoutes live behind
    original_router, possibly nested (app → v1_router → module routers).

    The mount prefix is NOT applied to the inner routes' .path — it hangs off
    the wrapper's include_context (a module router's route reads "/listings";
    the wire path is "/v1/listings"). Yields therefore carry the accumulated
    prefix alongside the route rather than mutating route.path: this walker
    runs at import time (boot guard) AND in tests, and mutation is not
    idempotent — a second walk would double-prefix.

    If FastAPI reshapes these internals the walker sees fewer routes rather
    than erroring — test_walker_reaches_current_routes fails loudly in that
    case, which is the tripwire to update this.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route, prefix + route.path
        elif type(route).__name__ == "_IncludedRouter":
            context = getattr(route, "include_context", None)
            mounted = prefix + getattr(context, "prefix", "")
            yield from _iter_api_routes(route.original_router.routes, mounted)


def _is_pydantic_model(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseModel)


def _models_in(annotation: Any) -> Iterator[type[BaseModel]]:
    """Yield every pydantic model inside an annotation.

    Bare X yields X. Typing constructs are unwrapped recursively via
    get_args: Annotated[X, Body()] → (X, Body()), X | None → (X, NoneType),
    list[X]/dict[str, X] and nests likewise. Wrapper metadata (Body(),
    NoneType, str) is never a BaseModel and has no model args, so it falls
    out naturally.
    """
    if _is_pydantic_model(annotation):
        yield annotation
        return
    for arg in get_args(annotation):
        yield from _models_in(arg)


def _is_generated(model: type[BaseModel]) -> bool:
    # Exact module or a submodule of it (bazaar_api.generated.*) — the dot
    # boundary matters: startswith without it would also match a hypothetical
    # "bazaar_api.generated_evil".
    module = model.__module__
    return module == GENERATED_MODULE or module.startswith(GENERATED_MODULE + ".")


def _contract_annotations(route: APIRoute, path: str) -> Iterator[tuple[str, Any]]:
    """(source-label, annotation) for every contract position on a route.

    path is the wire path from _iter_api_routes (route.path itself is
    unprefixed under lazy includes) — labels must name the real operation.
    """
    label = f"{sorted(route.methods or [])} {path}"
    yield f"{label} response_model", route.response_model
    for code, declaration in (route.responses or {}).items():
        if isinstance(declaration, dict) and "model" in declaration:
            yield f"{label} responses[{code!r}]['model']", declaration["model"]
    try:
        # eval_str=True: with `from __future__ import annotations` (which this
        # repo's modules use) param.annotation is a STRING, not the class, and
        # the provenance check would go blind. FastAPI resolves hints at route
        # registration, so this normally cannot fail — but "normally" is doing
        # work there (e.g. a TYPE_CHECKING-only name FastAPI didn't need), so
        # on failure raise with the route identified, not a bare NameError
        # crashing boot for every route.
        params = tuple(inspect.signature(route.endpoint, eval_str=True).parameters.values())
    except Exception as e:
        raise RuntimeError(
            f"{label}: cannot resolve endpoint annotations ({e}) — the "
            "provenance check needs evaluatable annotations on every route"
        ) from e
    for param in params:
        # In FastAPI handlers a BaseModel-annotated parameter is a request
        # body. Unannotated params are Parameter.empty; Depends/Path/Query
        # params are scalars — both fall out of the model walk.
        yield f"{label} parameter '{param.name}'", param.annotation


def assert_generated_contract_models(app: FastAPI) -> None:
    """Fail boot if any route uses a contract model not generated from the spec.

    Raises RuntimeError listing every offender. Non-model declarations
    (dict/None response models, scalar params) are not contract models and
    are ignored — the drift guard owns "is a model declared at all"; this
    guard owns "is the declared model the generated one".
    """
    offenders: list[str] = []
    for route, path in _iter_api_routes(app.routes):
        if _is_exempt(path):
            continue
        for source, annotation in _contract_annotations(route, path):
            for model in _models_in(annotation):
                if not _is_generated(model):
                    offenders.append(f"{source}: {model.__module__}.{model.__qualname__}")

    if offenders:
        listing = "\n".join(f"  {offender}" for offender in offenders)
        raise RuntimeError(
            f"hand-rolled contract model(s) detected — every model in a route "
            f"declaration must come from {GENERATED_MODULE} (codegen from "
            f"spec/openapi.yaml; run `pnpm gen`):\n{listing}\n"
            "The drift guard compares component names and cannot tell a "
            "shadow class from the generated model; this boot check can. "
            "(T283506756)"
        )
