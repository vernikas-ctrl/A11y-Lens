"""Task 2.3 — configuration loading, validation, and secret handling.

Several of these tests `monkeypatch.chdir(tmp_path)`. That is not incidental:
`Settings` reads `.env` relative to the working directory, and a real
`backend/.env` exists on a developer machine. Without moving out of that
directory, a test for "what happens when a required key is missing" would
quietly read the developer's real key and pass for the wrong reason.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    PLACEHOLDER_API_KEY,
    ConfigError,
    Settings,
    get_settings,
)

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"

REQUIRED = ("ANTHROPIC_API_KEY", "ACCESS_CODE")

# Long enough to satisfy the minimum-length rule, obviously fake to a reader.
VALID_CODE = "not-a-real-access-code"


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """No .env file, and no configuration inherited from the real environment."""
    monkeypatch.chdir(tmp_path)
    for key in (*REQUIRED, "ALLOWED_ORIGINS", "SCAN_TIMEOUT_MS",
                "DAILY_SCAN_LIMIT", "ENVIRONMENT", "ANTHROPIC_MODEL",
                "ANTHROPIC_EFFORT", "EXPLAIN_TIMEOUT_MS",
                "RATE_LIMIT_PER_MINUTE", "TRUSTED_PROXY_HOPS"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- The required-secret rule -----------------------------------------------

@pytest.mark.parametrize("missing", REQUIRED)
def test_a_missing_secret_is_fatal(isolated_env, monkeypatch, missing):
    """Absence must stop the server, not fall back to a default."""
    for key in REQUIRED:
        if key != missing:
            monkeypatch.setenv(key, VALID_CODE)

    with pytest.raises(ConfigError) as caught:
        get_settings()

    assert missing in str(caught.value)


def test_the_failure_message_says_what_to_do(isolated_env):
    """A traceback is not an instruction.

    Someone setting the project up for the first time needs the name of the
    file to create, not a validation dump.
    """
    with pytest.raises(ConfigError) as caught:
        get_settings()

    message = str(caught.value)
    assert ".env.example" in message
    assert ".env" in message
    assert "git-ignored" in message
    # Both missing keys reported at once, so the fix is not trial and error.
    for key in REQUIRED:
        assert key in message


def test_valid_configuration_loads(isolated_env, monkeypatch):
    for key in REQUIRED:
        monkeypatch.setenv(key, VALID_CODE)

    settings = get_settings()

    assert settings.access_code.get_secret_value() == VALID_CODE
    assert settings.allowed_origins == ["http://localhost:5173"]
    assert settings.scan_timeout_ms == 30_000
    assert settings.daily_scan_limit == 50


# --- Secrets must not leak into logs or tracebacks --------------------------

def test_secrets_are_masked_when_printed():
    """The most common way an API key reaches a log file is something printing
    a settings object. SecretStr makes that safe by default."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="sk-ant-super-secret-value",
        access_code=VALID_CODE,
    )

    rendered = repr(settings) + str(settings) + str(settings.model_dump())

    assert "sk-ant-super-secret-value" not in rendered
    assert VALID_CODE not in rendered
    assert "**********" in rendered


def test_reading_a_secret_is_explicit():
    """The real value is still reachable -- deliberately, and only on request."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="sk-ant-super-secret-value",
        access_code=VALID_CODE,
    )
    assert settings.anthropic_api_key.get_secret_value() == (
        "sk-ant-super-secret-value"
    )


# --- Individual settings ----------------------------------------------------

def test_allowed_origins_accepts_a_comma_separated_list():
    """Hosts' environment-variable fields take plain text, not JSON."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="k",
        access_code=VALID_CODE,
        allowed_origins="https://a.example , https://b.example",
    )
    assert settings.allowed_origins == ["https://a.example", "https://b.example"]


def test_a_short_access_code_is_rejected():
    """It is the only thing protecting the API budget on a public URL."""
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, anthropic_api_key="k", access_code="short")

    assert "12 characters" in str(caught.value)


@pytest.mark.parametrize("bad_timeout", [500, 300_000])
def test_scan_timeout_must_be_sane(bad_timeout):
    """Too low cannot load any real page; too high holds a worker hostage."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            anthropic_api_key="k",
            access_code=VALID_CODE,
            scan_timeout_ms=bad_timeout,
        )


def test_daily_scan_limit_may_be_zero_but_not_negative():
    """Zero is a real setting: it switches live scanning off and leaves the
    demo page working."""
    off = Settings(
        _env_file=None, anthropic_api_key="k", access_code=VALID_CODE,
        daily_scan_limit=0,
    )
    assert off.daily_scan_limit == 0

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, anthropic_api_key="k", access_code=VALID_CODE,
            daily_scan_limit=-1,
        )


# --- The placeholder API key ------------------------------------------------

def test_placeholder_key_is_allowed_in_development(isolated_env, monkeypatch):
    """Phases 2-4 never call Claude. Blocking local work on a key that is not
    needed yet would be pointless friction."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER_API_KEY)
    monkeypatch.setenv("ACCESS_CODE", VALID_CODE)

    settings = get_settings()

    assert settings.uses_placeholder_api_key is True
    assert settings.is_production is False


def test_placeholder_key_is_fatal_in_production(isolated_env, monkeypatch):
    """Deploying with an unset key should fail at startup, not on the first
    user's first scan."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER_API_KEY)
    monkeypatch.setenv("ACCESS_CODE", VALID_CODE)
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ConfigError) as caught:
        get_settings()

    assert "placeholder" in str(caught.value).lower()


def test_a_real_key_is_fine_in_production(isolated_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-looks-real-enough")
    monkeypatch.setenv("ACCESS_CODE", VALID_CODE)
    monkeypatch.setenv("ENVIRONMENT", "Production")  # case must not matter

    settings = get_settings()

    assert settings.is_production is True
    assert settings.uses_placeholder_api_key is False


# --- Caching ----------------------------------------------------------------

def test_settings_are_loaded_once(isolated_env, monkeypatch):
    """Configuration changing mid-process would be a bug, not a feature."""
    for key in REQUIRED:
        monkeypatch.setenv(key, VALID_CODE)

    assert get_settings() is get_settings()


# --- .env.example is documentation that must not go stale -------------------

def _documented_keys() -> set[str]:
    return {
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def test_env_example_documents_every_setting():
    """Task 2.3 requires .env.example to list every key the app reads.

    This is the test that keeps it true. Adding a setting to config.py and
    forgetting to document it is the single easiest way to leave someone unable
    to deploy, and nothing else would catch it.
    """
    expected = {name.upper() for name in Settings.model_fields}

    assert expected - _documented_keys() == set(), (
        "settings missing from backend/.env.example"
    )


def test_env_example_documents_nothing_invented():
    """The reverse drift: a key documented but no longer read, which sends
    someone configuring a value that does nothing."""
    expected = {name.upper() for name in Settings.model_fields}

    assert _documented_keys() - expected == set(), (
        "backend/.env.example lists keys the app does not read"
    )


def test_env_example_contains_no_real_secrets():
    """It is committed. A real key reaching it is the failure this project is
    most keen to avoid."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert PLACEHOLDER_API_KEY in text
    # Anthropic keys begin sk-ant-; the placeholder deliberately does not.
    assert "sk-ant-" not in text
