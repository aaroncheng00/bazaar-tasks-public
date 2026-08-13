"""Spec ⇄ app drift guard (T283279799).

Compares spec/openapi.yaml (the contract of record) against the runtime
schema FastAPI generates from the registered routes (app.openapi()). The
committed spec is the MVP contract; handlers arrive milestone by milestone,
so until the surface is fully populated the two legitimately differ — the
app is missing spec'd operations, and the catch-all in api.py adds
placeholder routes. Those two known deltas are whitelisted below; ANY other
difference fails the check.

What this catches (the drift that hurts):

  * a route is registered whose (path, method) is not in the spec
    — the app has left the contract
  * a registered route's operationId != the spec's
    — codegen (SDK, generated/models.py) names drift from the contract
  * a success or error response schema ref, requestBody schema ref, or
    parameter name disagrees with the spec
    — the shape of the contract drifted. Spec-side component refs
    (components/responses, components/parameters) are resolved before
    comparison, so `"409": {$ref: .../ListingAlreadySold}` must match the
    handler's declared 409 model. The guard sees status codes and schema
    components; the error `code` STRING inside the envelope (review_exists
    vs listing_already_sold) lives in the component's description/example
    and stays a code-review concern
  * a whitelisted spec operation gains a handler, or a whitelisted extra
    route is removed
    — the whitelist itself has drifted from reality; stale entries fail so
    the file shrinks to zero as the surface lands, and the exception list
    can never silently rot

Checked-into-notion ratchet: as each milestone (S1, P2, P1, S2 per the
spec's tags) lands its handlers, delete entries from KNOWN_UNIMPLEMENTED.
When it is empty, the runtime schema must equal the spec exactly.

Registered 501 stubs (the scaffolding handlers in modules/*) count as
UNIMPLEMENTED: a route whose handler raises HTTP_501_NOT_IMPLEMENTED keeps
its whitelist entry, because registration is not implementation — a stub
cannot diverge from a contract it does not yet serve, and forcing stubs to
carry full declarations would churn every in-flight implementation PR.
main() detects them from endpoint source via stub_route_keys(); compare()
takes them as an optional third argument so synthetic-doc tests are
unaffected.

Run:  uv run python -m bazaar_api._maint.check_spec_drift   (from apps/api)
CI:   the `drift` job in .github/workflows/ci.yml runs exactly this.
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# .../apps/api/src/bazaar_api/_maint/check_spec_drift.py → repo root
REPO_ROOT = Path(__file__).resolve().parents[5]
SPEC_PATH = REPO_ROOT / "spec" / "openapi.yaml"

# Paths FastAPI generates itself; they are plumbing, not contract.
IGNORED_RUNTIME_PATHS = frozenset({"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})

# FastAPI appends a validation error block to every operation, while the
# spec models invalid input as the domain 400 — 422 presence/absence is
# FastAPI plumbing, not contract. The spec's `default` response (always the
# shared Error component) has no FastAPI-declared counterpart, so its
# presence/absence is not drift either; the domain error codes (400/401/
# 403/404/409/429/503) around it ARE compared.
IGNORED_RESPONSE_CODES = frozenset({"422", "default"})

# (path, method) the spec defines that have no handler yet. api.py's
# catch-all answers them with 501, so callers get a loud failure; the drift
# this task guards against is a handler that DIVERGES from the spec, not a
# missing one. Remove entries as milestones land; a stale entry is an error.
KNOWN_UNIMPLEMENTED: frozenset[tuple[str, str]] = frozenset(
    {
        ("post", "/v1/listings"),
        ("get", "/v1/listings"),
        ("get", "/v1/listings/{listing_id}"),
        ("patch", "/v1/listings/{listing_id}"),
        ("post", "/v1/listings/{listing_id}/images"),
        ("post", "/v1/listings/{listing_id}/images/attach"),
        ("post", "/v1/listings/{listing_id}/remove"),
        ("get", "/v1/reviews"),
        ("get", "/v1/reviews/aggregate"),
    }
)

# Runtime routes that are intentionally not in the spec. /smoke/* is the
# RLS/migration smoke surface, retired once real tables land. The /v1 501
# catch-all no longer needs entries here: it is registered with
# include_in_schema=False (api.py), so it never appears in app.openapi().
# A stale entry is an error.
KNOWN_EXTRA_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("get", "/smoke/docs"),
        ("post", "/smoke/echo"),
    }
)

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "options", "head", "trace")


def resolve_local_ref(doc: dict[str, Any], node: Any) -> Any:
    """Resolve a single local `$ref` (#/...) against doc; pass anything else
    through unchanged. An unresolvable ref raises ValueError — a broken ref
    in the committed spec is a CI failure, not a comparison result.
    """
    if not (isinstance(node, dict) and set(node) == {"$ref"}):
        return node
    ref = str(node["$ref"])
    if not ref.startswith("#/"):
        return node
    target: Any = doc
    for part in ref[2:].split("/"):
        if not isinstance(target, dict) or part not in target:
            raise ValueError(f"unresolvable $ref in spec: {ref}")
        target = target[part]
    return target


def operations(
    doc: dict[str, Any], *, resolve_refs: bool = False
) -> dict[tuple[str, str], dict[str, Any]]:
    """{(method, path): operation object} for every operation in a spec doc.

    With resolve_refs, response and parameter entries that are single local
    `$ref`s are dereferenced against the doc's components. The committed spec
    expresses every error response as a components/responses ref and every
    parameter as a components/parameters ref; FastAPI's runtime schema always
    inlines. Resolving spec-side puts both in the same comparable shape.
    """
    ops: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in (doc.get("paths") or {}).items():
        if path in IGNORED_RUNTIME_PATHS:
            continue
        for method, op in (item or {}).items():
            if method not in HTTP_METHODS or not isinstance(op, dict):
                continue
            if resolve_refs:
                op = dict(op)
                if op.get("responses"):
                    op["responses"] = {
                        code: resolve_local_ref(doc, resp) for code, resp in op["responses"].items()
                    }
                if op.get("parameters"):
                    op["parameters"] = [resolve_local_ref(doc, param) for param in op["parameters"]]
            ops[(method, path)] = op
    return ops


def response_schema_refs(op: dict[str, Any]) -> dict[str, str | None]:
    """status code -> json-schema $ref target for EVERY declared response.

    Success and error responses alike: the spec's error contract (400/401/
    403/404/409/429/503, each a named components/responses entry wrapping a
    schema component) is exactly the drift this guard exists to catch — a
    handler declaring 409 with the wrong model, or omitting a spec'd 403,
    fails here. `None` means the response has no application/json schema.
    Codes in IGNORED_RESPONSE_CODES (422, default) are dropped: they are
    FastAPI/spec authoring asymmetries, not contract.

    The check compares refs, not dereferenced schemas: handlers must name
    the same component the contract names, and datamodel-codegen maps
    component names 1:1 onto the model classes handlers return.
    """
    refs: dict[str, str | None] = {}
    for code, resp in (op.get("responses") or {}).items():
        code = str(code)
        if code in IGNORED_RESPONSE_CODES:
            continue
        schema = ((resp.get("content") or {}).get("application/json") or {}).get("schema") or {}
        refs[code] = schema.get("$ref")
    return refs


def request_schema_ref(op: dict[str, Any]) -> str | None:
    """$ref target of the operation's application/json request body, if any."""
    body = op.get("requestBody") or {}
    schema = (body.get("content") or {}).get("application/json", {}).get("schema") or {}
    return schema.get("$ref")


def parameter_names(op: dict[str, Any]) -> set[str]:
    """Declared parameter names (path/query/header). Existence, not shape."""
    return {p.get("name", "") for p in op.get("parameters") or []}


def describe(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


def stub_route_keys(routes: Iterable[Any]) -> frozenset[tuple[str, str]]:
    """(method, path) of registered routes whose handler is a 501 stub.

    Detection reads the endpoint's source for the HTTP_501_NOT_IMPLEMENTED
    raise — the OpenAPI doc cannot distinguish a stub from a real handler
    (stubs declare response models too). Real handlers never raise 501; the
    /v1 catch-all does, and is filtered out by compare() (its path is not in
    the spec).

    This FastAPI version nests included routers as _IncludedRouter objects
    instead of flattening app.routes, so walk effective_candidates() down to
    the leaf route contexts, which carry the fully-prefixed path + endpoint.
    """
    keys: set[tuple[str, str]] = set()

    def visit(route: Any) -> None:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            for candidate in candidates():
                visit(candidate)
            return
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        endpoint = getattr(route, "endpoint", None)
        if not methods or not isinstance(path, str) or endpoint is None:
            return
        try:
            source = inspect.getsource(endpoint)
        except (OSError, TypeError):
            return
        if "HTTP_501_NOT_IMPLEMENTED" in source:
            keys.update((method.lower(), path) for method in methods)

    for top_level in routes:
        visit(top_level)
    return frozenset(keys)


@dataclass
class Drift:
    """Accumulates differences; the guard fails iff `problems` is non-empty."""

    problems: list[str] = field(default_factory=list)
    tolerated: list[str] = field(default_factory=list)

    def problem(self, message: str) -> None:
        self.problems.append(message)

    def tolerate(self, message: str) -> None:
        self.tolerated.append(message)


def compare(
    spec_doc: dict[str, Any],
    runtime_doc: dict[str, Any],
    stub_keys: Iterable[tuple[str, str]] = frozenset(),
) -> Drift:
    drift = Drift()
    spec_ops = operations(spec_doc, resolve_refs=True)
    runtime_ops = operations(runtime_doc)

    # 501 stubs for SPEC'D operations are subtracted from the runtime surface:
    # they keep their KNOWN_UNIMPLEMENTED entries (registration is not
    # implementation). The /v1 catch-all also raises 501 but is not in the
    # spec, so the intersection leaves it visible to KNOWN_EXTRA_ROUTES.
    effective_runtime = set(runtime_ops) - (set(stub_keys) & set(spec_ops))

    # --- coverage: which spec operations are implemented, which runtime ---
    # --- routes are unexpected; stale whitelist entries are failures.   ---
    implemented = sorted(set(spec_ops) & effective_runtime)
    unimplemented = set(spec_ops) - effective_runtime
    extra = effective_runtime - set(spec_ops)

    for key in sorted(unimplemented - KNOWN_UNIMPLEMENTED):
        drift.problem(
            f"{describe(*key)} is in the spec but has no handler and is not whitelisted "
            "— implement it or add it to KNOWN_UNIMPLEMENTED"
        )
    for key in sorted(KNOWN_UNIMPLEMENTED - unimplemented):
        drift.problem(
            f"{describe(*key)} is whitelisted in KNOWN_UNIMPLEMENTED but a handler now "
            "exists (or the spec dropped it) — remove the stale whitelist entry"
        )
    for key in sorted(extra - KNOWN_EXTRA_ROUTES):
        drift.problem(
            f"{describe(*key)} is served by the app but is not in the spec — the app "
            "has left the contract; spec it or remove the route"
        )
    for key in sorted(KNOWN_EXTRA_ROUTES - extra):
        drift.problem(
            f"{describe(*key)} is whitelisted in KNOWN_EXTRA_ROUTES but the app no "
            "longer serves it — remove the stale whitelist entry"
        )

    for key in sorted(unimplemented & KNOWN_UNIMPLEMENTED):
        drift.tolerate(f"{describe(*key)}: spec'd, no handler yet (whitelisted)")
    for key in sorted(extra & KNOWN_EXTRA_ROUTES):
        drift.tolerate(f"{describe(*key)}: runtime-only route (whitelisted)")

    # --- per-operation contract shape, for everything implemented ---
    for key in implemented:
        spec_op, runtime_op = spec_ops[key], runtime_ops[key]
        name = describe(*key)

        spec_opid = spec_op.get("operationId")
        runtime_opid = runtime_op.get("operationId")
        if spec_opid != runtime_opid:
            drift.problem(
                f"{name}: operationId drift — spec {spec_opid!r} vs app {runtime_opid!r} "
                "(set operation_id= on the route; codegen names depend on it)"
            )

        spec_refs = response_schema_refs(spec_op)
        runtime_refs = response_schema_refs(runtime_op)
        if spec_refs != runtime_refs:
            drift.problem(f"{name}: response schema drift — spec {spec_refs} vs app {runtime_refs}")

        if request_schema_ref(spec_op) != request_schema_ref(runtime_op):
            drift.problem(
                f"{name}: request body schema drift — spec "
                f"{request_schema_ref(spec_op)!r} vs app {request_schema_ref(runtime_op)!r}"
            )

        spec_params = parameter_names(spec_op)
        runtime_params = parameter_names(runtime_op)
        if spec_params != runtime_params:
            drift.problem(
                f"{name}: parameter drift — spec {sorted(spec_params)} vs app "
                f"{sorted(runtime_params)}"
            )

    return drift


def main() -> int:
    spec_doc: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text())

    # Imported here so `--help`-style introspection of this module never
    # boots the app; importing bazaar_api.main reconfigures process logging
    # and validates settings as a side effect.
    from bazaar_api.main import app

    drift = compare(spec_doc, app.openapi(), stub_route_keys(app.routes))

    print(f"spec: {SPEC_PATH}")
    for message in drift.tolerated:
        print(f"  ok (whitelisted): {message}")

    if drift.problems:
        print("\nSPEC DRIFT DETECTED — the app and spec/openapi.yaml disagree:")
        for message in drift.problems:
            print(f"  FAIL: {message}")
        print(
            "\nThe spec is the contract of record. Either change the code to "
            "match it, or change the spec in the same PR that changes the "
            "code. Whitelists must shrink as handlers land — stale entries fail."
        )
        return 1

    print("\nno drift: every registered route matches the spec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
