"""Security: Idempotency-Key length/charset validation."""

from bazaar_api.middleware.idempotency import _IDEMPOTENCY_KEY_RE, MAX_IDEMPOTENCY_KEY_LEN
from bazaar_api.middleware.idempotency import _redis_key as _redis_key_fn


def test_valid_idempotency_keys() -> None:
    valid = ["key-123", "abc.def_123", "A" * MAX_IDEMPOTENCY_KEY_LEN]
    for k in valid:
        assert len(k) <= MAX_IDEMPOTENCY_KEY_LEN
        assert _IDEMPOTENCY_KEY_RE.match(k)


def test_invalid_idempotency_keys() -> None:
    invalid = [
        "has space",
        "has\nnewline",
        "<inject>",
        "a" * (MAX_IDEMPOTENCY_KEY_LEN + 1),
        "../../etc",
        "key; rm",
    ]
    for k in invalid:
        assert len(k) > MAX_IDEMPOTENCY_KEY_LEN or not _IDEMPOTENCY_KEY_RE.match(k)


def test_redis_key_uses_template_not_raw_path() -> None:
    """Ensure _redis_key uses route template to avoid cardinality blowup."""

    # Mock request with route path template
    class MockRoute:
        path = "/v1/listings/{id}"

    class MockURL:
        path = "/v1/listings/lst_123456"

    scope = {"route": MockRoute(), "path": "/v1/listings/lst_123456"}

    # Create minimal Request-like object with scope and url
    class FakeRequest:
        def __init__(self) -> None:
            self.scope = scope
            self.url = MockURL()

    req = FakeRequest()
    key = _redis_key_fn("app-a", req, "idem-123")  # type: ignore[arg-type]
    assert "/v1/listings/{id}" in key
    assert "lst_123456" not in key
    assert key.startswith("idem:app-a:")
