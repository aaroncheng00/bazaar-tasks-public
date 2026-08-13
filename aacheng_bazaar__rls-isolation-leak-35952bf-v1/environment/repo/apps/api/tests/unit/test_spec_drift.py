"""Tests for the spec drift guard (bazaar_api._maint.check_spec_drift, T283279799).

Two layers: compare() is exercised against synthetic spec/runtime docs (each
failure mode, plus stale-whitelist detection and the 422 exemption), and
main()/compare() are run against the real app + committed spec to prove the
tree is clean right now.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from bazaar_api._maint.check_spec_drift import (
    KNOWN_EXTRA_ROUTES,
    KNOWN_UNIMPLEMENTED,
    SPEC_PATH,
    compare,
    main,
    operations,
    stub_route_keys,
)
from bazaar_api.main import app


def _doc(
    ops: dict[tuple[str, str], dict[str, Any]],
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal openapi doc from {(method, path): operation}."""
    paths: dict[str, Any] = {}
    for (method, path), op in ops.items():
        paths.setdefault(path, {})[method] = op
    doc: dict[str, Any] = {"paths": paths}
    if components:
        doc["components"] = components
    return doc


_HEALTHZ = ("get", "/healthz")  # in no whitelist — free for synthetic use


def test_compare_accepts_current_tree() -> None:
    spec_doc: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text())
    drift = compare(spec_doc, app.openapi(), stub_route_keys(app.routes))
    assert drift.problems == []
    # The whitelisted surface must be non-empty and reported — a guard that
    # silently tolerates nothing is probably broken, not clean.
    assert drift.tolerated


def test_main_passes_on_current_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    assert "no drift" in capsys.readouterr().out


def test_unimplemented_spec_op_without_whitelist_fails() -> None:
    spec = _doc({("get", "/v1/things"): {"operationId": "listThings"}})
    drift = compare(spec, _doc({}))
    assert any("GET /v1/things" in p and "no handler" in p for p in drift.problems)


def test_stale_unimplemented_whitelist_entry_fails() -> None:
    # ("get", "/v1/reviews/aggregate") is whitelisted as unimplemented, so a
    # tree where it HAS a real handler must fail — the whitelist entry has to
    # be deleted. (Picked because no other whitelist entry's description
    # contains it as a substring — the assertions match on substrings.)
    key = ("get", "/v1/reviews/aggregate")
    assert key in KNOWN_UNIMPLEMENTED
    op = {"operationId": "getReviewAggregate"}
    drift = compare(_doc({key: op}), _doc({key: op}))
    assert any("stale whitelist" in p and "GET /v1/reviews/aggregate" in p for p in drift.problems)


def test_stub_route_keeps_its_whitelist_entry() -> None:
    # Same shape as the stale-entry test, but the runtime handler is a 501
    # stub: registration is not implementation, so the entry must NOT go
    # stale — the op stays whitelisted-unimplemented and skips comparison.
    key = ("get", "/v1/reviews/aggregate")
    assert key in KNOWN_UNIMPLEMENTED
    op = {"operationId": "getReviewAggregate"}
    drift = compare(_doc({key: op}), _doc({key: op}), stub_keys=frozenset({key}))
    assert not any(
        "stale whitelist" in p and "GET /v1/reviews/aggregate" in p for p in drift.problems
    )
    assert any("GET /v1/reviews/aggregate" in t and "no handler yet" in t for t in drift.tolerated)


def test_stub_route_keys_finds_registered_stubs() -> None:
    keys = stub_route_keys(app.routes)
    # crud.py's create-listing handler is a registered 501 stub on this tree…
    assert ("post", "/v1/listings") in keys
    # …while the implemented keys-create handler is not one.
    assert ("post", "/v1/apps/{app_id}/keys") not in keys


def test_extra_route_fails() -> None:
    drift = compare(_doc({}), _doc({("get", "/v1/sneaky"): {"operationId": "sneaky"}}))
    assert any("GET /v1/sneaky" in p and "not in the spec" in p for p in drift.problems)


def test_stale_extra_route_whitelist_entry_fails() -> None:
    key = ("get", "/smoke/docs")
    assert key in KNOWN_EXTRA_ROUTES
    # The app no longer serves /smoke/docs, so its whitelist entry is stale.
    drift = compare(_doc({}), _doc({}))
    assert any("stale whitelist" in p and "GET /smoke/docs" in p for p in drift.problems)


def test_operation_id_drift_fails() -> None:
    spec = _doc({_HEALTHZ: {"operationId": "healthz"}})
    runtime = _doc({_HEALTHZ: {"operationId": "healthz_healthz_get"}})
    drift = compare(spec, runtime)
    assert any("operationId drift" in p for p in drift.problems)


def test_response_schema_drift_fails() -> None:
    spec = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Healthz"}}
                        }
                    }
                },
            }
        }
    )
    runtime = _doc({_HEALTHZ: {"operationId": "healthz", "responses": {"200": {}}}})
    drift = compare(spec, runtime)
    assert any("response schema drift" in p for p in drift.problems)


def test_request_body_drift_fails() -> None:
    spec = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "requestBody": {
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}
                },
            }
        }
    )
    runtime = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "requestBody": {
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/B"}}}
                },
            }
        }
    )
    drift = compare(spec, runtime)
    assert any("request body schema drift" in p for p in drift.problems)


def test_parameter_drift_fails() -> None:
    spec = _doc({_HEALTHZ: {"operationId": "healthz", "parameters": [{"name": "limit"}]}})
    runtime = _doc({_HEALTHZ: {"operationId": "healthz", "parameters": [{"name": "cursor"}]}})
    drift = compare(spec, runtime)
    assert any("parameter drift" in p for p in drift.problems)


def test_fastapi_422_block_is_not_drift() -> None:
    # FastAPI appends a 422 validation-error response to every operation; the
    # spec models invalid input as the domain 400. Presence must not fail.
    ok_200 = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Healthz"}}}}
    spec = _doc({_HEALTHZ: {"operationId": "healthz", "responses": {"200": ok_200}}})
    runtime = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {
                    "200": ok_200,
                    "422": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HTTPValidationError"}
                            }
                        }
                    },
                },
            }
        }
    )
    # Coverage noise (stale whitelist entries for the real, absent spec
    # surface) is expected on synthetic docs; what must NOT appear is a
    # response-schema complaint about the 422 block.
    problems = compare(spec, runtime).problems
    assert not any("response schema drift" in p for p in problems)


def test_whitelists_reference_real_spec_operations() -> None:
    # A typo'd whitelist entry would fail as "stale" at compare() time; this
    # pins the intent directly so the error message points at the typo.
    spec_doc: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text())
    spec_keys = set(operations(spec_doc))
    assert KNOWN_UNIMPLEMENTED <= spec_keys


_ERROR_COMPONENTS = {
    "responses": {
        "Conflict": {
            "description": "review_exists",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
            },
        }
    },
    "parameters": {
        "IdempotencyKey": {
            "name": "Idempotency-Key",
            "in": "header",
            "required": False,
            "schema": {"type": "string", "format": "uuid"},
        }
    },
}


def _json_response(ref: str) -> dict[str, Any]:
    return {"content": {"application/json": {"schema": {"$ref": ref}}}}


def test_error_response_component_refs_are_compared() -> None:
    # Spec authors reference components/responses; FastAPI inlines. After
    # spec-side resolution the two must compare equal.
    op_spec = {
        "operationId": "healthz",
        "responses": {
            "200": _json_response("#/components/schemas/Healthz"),
            "409": {"$ref": "#/components/responses/Conflict"},
        },
    }
    op_runtime = {
        "operationId": "healthz",
        "responses": {
            "200": _json_response("#/components/schemas/Healthz"),
            "409": _json_response("#/components/schemas/ErrorEnvelope"),
        },
    }
    problems = compare(
        _doc({_HEALTHZ: op_spec}, components=_ERROR_COMPONENTS), _doc({_HEALTHZ: op_runtime})
    ).problems
    assert not any("response schema drift" in p for p in problems)


def test_error_response_code_missing_fails() -> None:
    # The handler omits the spec'd 409 entirely.
    spec = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {"409": {"$ref": "#/components/responses/Conflict"}},
            }
        },
        components=_ERROR_COMPONENTS,
    )
    runtime = _doc({_HEALTHZ: {"operationId": "healthz", "responses": {}}})
    drift = compare(spec, runtime)
    assert any("response schema drift" in p for p in drift.problems)


def test_error_response_wrong_model_fails() -> None:
    # The handler declares 409 but with the wrong schema component.
    spec = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {"409": {"$ref": "#/components/responses/Conflict"}},
            }
        },
        components=_ERROR_COMPONENTS,
    )
    runtime = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {"409": _json_response("#/components/schemas/Listing")},
            }
        }
    )
    drift = compare(spec, runtime)
    assert any("response schema drift" in p for p in drift.problems)


def test_default_response_is_not_drift() -> None:
    # The spec's `default` response has no FastAPI-declared counterpart; its
    # presence on the spec side must not fail, and it must resolve cleanly
    # through components/responses.
    spec = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {
                    "200": _json_response("#/components/schemas/Healthz"),
                    "default": {"$ref": "#/components/responses/Conflict"},
                },
            }
        },
        components=_ERROR_COMPONENTS,
    )
    runtime = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {"200": _json_response("#/components/schemas/Healthz")},
            }
        }
    )
    problems = compare(spec, runtime).problems
    assert not any("response schema drift" in p for p in problems)


def test_parameter_component_refs_resolve() -> None:
    # Without resolution the spec side produces an empty-string name for a
    # $ref'd parameter and every op would report parameter drift.
    spec = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "parameters": [{"$ref": "#/components/parameters/IdempotencyKey"}],
            }
        },
        components=_ERROR_COMPONENTS,
    )
    runtime = _doc(
        {_HEALTHZ: {"operationId": "healthz", "parameters": [{"name": "Idempotency-Key"}]}}
    )
    problems = compare(spec, runtime).problems
    assert not any("parameter drift" in p for p in problems)


def test_unresolvable_ref_raises() -> None:
    spec = _doc(
        {
            _HEALTHZ: {
                "operationId": "healthz",
                "responses": {"404": {"$ref": "#/components/responses/DoesNotExist"}},
            }
        },
        components=_ERROR_COMPONENTS,
    )
    with pytest.raises(ValueError, match="unresolvable \\$ref"):
        compare(spec, _doc({_HEALTHZ: {"operationId": "healthz"}}))
