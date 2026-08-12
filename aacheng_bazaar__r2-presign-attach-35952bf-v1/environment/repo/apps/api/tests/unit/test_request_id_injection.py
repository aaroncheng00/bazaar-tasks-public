"""Security: request_id injection guard."""

from bazaar_api.middleware.request_id import _REQUEST_ID_RE, MAX_REQUEST_ID_LEN, RequestIdMiddleware


def test_valid_request_ids_pass_regex() -> None:
    valid = ["req_abc123", "abc123", "my-request.id_123"]
    for v in valid:
        assert len(v) <= MAX_REQUEST_ID_LEN
        assert _REQUEST_ID_RE.match(v)


def test_invalid_request_ids_fail_regex() -> None:
    invalid = [
        "has space",
        "has\nnewline",
        "has\r",
        "has\t",
        "a" * (MAX_REQUEST_ID_LEN + 1),
        "../../etc/passwd",
        "<script>",
        "id; rm -rf",
    ]
    for v in invalid:
        if len(v) > MAX_REQUEST_ID_LEN:
            assert len(v) > MAX_REQUEST_ID_LEN
        else:
            assert not _REQUEST_ID_RE.match(v)


def test_resolve_request_id_mints_on_invalid() -> None:
    # Too long => mint
    long_id = "a" * (MAX_REQUEST_ID_LEN + 1)
    scope: dict[str, object] = {"headers": [(b"x-request-id", long_id.encode())]}
    resolved = RequestIdMiddleware._resolve_request_id(scope)
    assert resolved != long_id
    assert resolved.startswith("req_")

    # Newline injection => mint
    scope2: dict[str, object] = {"headers": [(b"x-request-id", b"bad\nid")]}
    resolved2 = RequestIdMiddleware._resolve_request_id(scope2)
    assert "\n" not in resolved2
    assert resolved2.startswith("req_")

    # Valid => echo
    scope3: dict[str, object] = {"headers": [(b"x-request-id", b"valid-123_abc")]}
    resolved3 = RequestIdMiddleware._resolve_request_id(scope3)
    assert resolved3 == "valid-123_abc"


def test_resolve_request_id_mints_when_missing() -> None:
    scope: dict[str, object] = {"headers": []}
    resolved = RequestIdMiddleware._resolve_request_id(scope)
    assert resolved.startswith("req_")
    assert len(resolved) <= MAX_REQUEST_ID_LEN
