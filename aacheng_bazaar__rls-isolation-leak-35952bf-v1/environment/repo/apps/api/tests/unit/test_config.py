"""The BAZAAR_ env prefix: wiring, safe-side failure, and the legacy-name guard.

Every other test monkeypatches settings attributes directly, which bypasses
env parsing entirely — that's how an unwired env name slipped through with a
green suite. These exercise the actual env-var names.
"""

import logging

import pytest

from bazaar_api.config import Settings
from bazaar_api.main import check_unprefixed_env


def test_prefixed_env_var_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAZAAR_DEV_SKIP_HMAC", "true")
    assert Settings().dev_skip_hmac is True


def test_bare_env_var_is_safely_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # The failure mode points the safe way: an unprefixed name is silently
    # dropped and HMAC stays enforced. (The startup guard makes it visible.)
    monkeypatch.delenv("BAZAAR_DEV_SKIP_HMAC", raising=False)
    monkeypatch.setenv("DEV_SKIP_HMAC", "true")
    assert Settings().dev_skip_hmac is False


def test_env_default_is_fail_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    # A missing BAZAAR_ENV must resolve to the restrictive value, so a partial
    # migration (renamed BAZAAR_DEV_SKIP_HMAC, stale bare ENV) refuses to boot
    # rather than starting with auth bypassed.
    monkeypatch.delenv("BAZAAR_ENV", raising=False)
    assert Settings().env == "prod"


def test_partial_migration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # The reviewer's probe: renamed flag + stale bare ENV must NOT boot with
    # the escape hatch active. env now defaults to prod, so the combination
    # trips validate_dev_flags.
    monkeypatch.setenv("BAZAAR_DEV_SKIP_HMAC", "true")
    monkeypatch.delenv("BAZAAR_ENV", raising=False)
    s = Settings()
    from bazaar_api.main import validate_dev_flags

    monkeypatch.setattr("bazaar_api.main.settings", s)
    with pytest.raises(RuntimeError, match="refusing to boot"):
        validate_dev_flags()


def test_guard_warns_on_bare_non_auth_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="bazaar_api.main"):
        check_unprefixed_env({"REDIS_URL": "redis://localhost:6379/0"}, set())
    assert "ignoring unprefixed REDIS_URL" in caplog.text
    assert "BAZAAR_REDIS_URL" in caplog.text


def test_guard_silent_when_prefixed_present_in_environ(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="bazaar_api.main"):
        check_unprefixed_env({"REDIS_URL": "redis://x", "BAZAAR_REDIS_URL": "redis://y"}, set())
    assert "REDIS_URL" not in caplog.text


def test_guard_silent_when_prefixed_present_in_env_file(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # BAZAAR_ENV supplied via .env (the documented local setup) must count as
    # set — otherwise tooling-injected bare ENV would escalate falsely.
    with caplog.at_level(logging.WARNING, logger="bazaar_api.main"):
        check_unprefixed_env(
            {"DATABASE_URL": "postgres://platform-injected"}, {"BAZAAR_DATABASE_URL"}
        )
    assert "DATABASE_URL" not in caplog.text


def test_guard_escalates_on_bare_auth_deciding_names() -> None:
    # ENV and DEV_SKIP_HMAC decide whether auth is enforced — a stale bare
    # value stops the boot, not just a log line.
    with pytest.raises(RuntimeError, match="stale unprefixed ENV"):
        check_unprefixed_env({"ENV": "dev"}, set())
    with pytest.raises(RuntimeError, match="stale unprefixed DEV_SKIP_HMAC"):
        check_unprefixed_env({"DEV_SKIP_HMAC": "true"}, set())


def test_guard_escalation_also_respects_env_file() -> None:
    # Prefixed name present in .env → the bare name is platform noise, not an
    # operator mistake. No escalation, no warning.
    check_unprefixed_env({"ENV": "staging"}, {"BAZAAR_ENV"})


def test_guard_detects_bare_names_in_env_file(caplog: pytest.LogCaptureFixture) -> None:
    # A stale .env is the common case (the README points everyone there) — the
    # guard must see bare names there too, not just in the process env.
    with pytest.raises(RuntimeError, match="stale unprefixed ENV"):
        check_unprefixed_env({}, {"ENV"})

    with caplog.at_level(logging.WARNING, logger="bazaar_api.main"):
        check_unprefixed_env({}, {"KEYS"})
    assert "ignoring unprefixed KEYS" in caplog.text
