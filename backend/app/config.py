"""Every setting the app reads, in one place.

Task 2.3. Nothing configurable is allowed to be hard-coded anywhere else: a
value buried in a function is a value nobody can change at deploy time without
a code edit, and a secret buried in a function is a secret in git forever.

Two rules this file exists to enforce:

1. **Secrets never appear in code.** They arrive from the environment, locally
   via `backend/.env` (git-ignored), in production via the host's dashboard.
   `backend/.env.example` is the committed list of key names with no real
   values.
2. **A missing secret stops the server at startup**, with a message saying
   which key and what to do -- not three hours later on the first real request.

The secrets are typed `SecretStr`, so printing a `Settings` object, logging it,
or letting it surface in a stack trace shows `**********` instead of the value.
Reading the real value takes an explicit `.get_secret_value()`, which is easy
to grep for in review.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# A fresh clone gets this in .env so the server will boot during Phases 2-4,
# which never call Claude. Phase 5 is the first code that needs a real key, and
# `uses_placeholder_api_key` below is what warns that it is still unset.
PLACEHOLDER_API_KEY = "paste-your-anthropic-api-key-here"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid.

    A distinct type so `main.py` can catch exactly this and print something a
    human can act on, rather than swallowing unrelated failures.
    """


class Settings(BaseSettings):
    """Validated application configuration."""

    model_config = SettingsConfigDict(
        # Relative to the working directory, and the backend is run from
        # backend/ -- so this is backend/.env.
        env_file=".env",
        env_file_encoding="utf-8",
        # Real environments carry plenty of unrelated variables (PATH, PORT,
        # whatever the host injects). Ignore them instead of failing.
        extra="ignore",
        case_sensitive=False,
    )

    # --- Secrets. No defaults: the whole point is that absence is fatal. ---

    anthropic_api_key: SecretStr = Field(
        description="Claude API key. Console -> API keys. Never commit this.",
    )
    access_code: SecretStr = Field(
        description="Shared code that unlocks live scanning.",
    )

    # --- Everything else has a working default. ---

    # NoDecode is load-bearing. Without it, pydantic-settings tries to JSON-
    # decode any list-typed field at the source, before validators run, so
    # `ALLOWED_ORIGINS=http://localhost:5173` in a .env file fails to parse
    # before `split_comma_separated` below ever gets a chance to handle it.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173"],
        description="Origins the browser may call this API from (CORS). "
                    "Comma-separated. Vite's dev server is the local default.",
    )
    scan_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=120_000,
        description="How long a single page may take to load before giving up.",
    )

    # --- Phase 5: the explanation call. -------------------------------------
    #
    # The model is configuration and not a constant in the code because the
    # choice is a cost decision, and a cost decision has to be changeable
    # without a deploy. Opus 5.5 is the default: the explanations are the part
    # of this product a person actually reads.
    anthropic_model: str = Field(
        default="claude-opus-5-5",
        description="Model that writes the explanations. Cheaper alternatives: "
                    "claude-sonnet-5-5, claude-haiku-5-5.",
    )
    anthropic_effort: str = Field(
        default="low",
        description="How much thinking the model does before answering: low, "
                    "medium, high, xhigh or max. Thinking is billed as output, "
                    "so this is the main cost dial after the model itself.",
    )
    explain_timeout_ms: int = Field(
        default=60_000,
        ge=1_000,
        le=300_000,
        description="How long the explanation call may take before the scan "
                    "gives up on it and returns findings without explanations.",
    )

    # --- Phase 6: the gate and the ceiling. ---------------------------------

    rate_limit_per_minute: int = Field(
        default=5,
        ge=1,
        le=600,
        description="Requests one address may make per minute. A third line of "
                    "defence behind the access code and the daily ceiling, so "
                    "it is deliberately modest rather than clever.",
    )
    trusted_proxy_hops: int = Field(
        default=0,
        ge=0,
        le=4,
        description="How many proxies sit in front of this app. 0 locally, "
                    "where the connection address is the truth. Behind one "
                    "host proxy it is 1. Getting this wrong breaks rate "
                    "limiting in one direction or the other -- see "
                    "app/limits.py:client_key.",
    )

    @field_validator("anthropic_effort")
    @classmethod
    def check_effort(cls, value: str) -> str:
        """A typo here would come back as a 400 from the API on the first real
        scan, which is a confusing place to discover a misspelt setting."""
        allowed = ("low", "medium", "high", "xhigh", "max")
        cleaned = value.strip().lower()
        if cleaned not in allowed:
            raise ValueError(f"must be one of {', '.join(allowed)}")
        return cleaned
    daily_scan_limit: int = Field(
        default=50,
        ge=0,
        description="Hard ceiling on scans per day across all users. The thing "
                    "that stops a leaked access code emptying the budget. 0 "
                    "blocks live scanning entirely.",
    )
    environment: str = Field(
        default="development",
        description="development or production. Production refuses to start "
                    "on a placeholder API key.",
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_comma_separated(cls, value: object) -> object:
        """Accept `a,b` from .env as well as a JSON array.

        Without this, pydantic-settings expects a JSON array for a list field,
        which means writing `ALLOWED_ORIGINS=["http://x"]` in a .env file --
        easy to get subtly wrong, and unlike every other host's env-var UI.
        """
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("access_code")
    @classmethod
    def reject_weak_access_code(cls, value: SecretStr) -> SecretStr:
        """The access code is the only thing standing between a public URL and
        the API budget, so a two-character one is a real problem, not a style
        preference."""
        if len(value.get_secret_value()) < 12:
            raise ValueError(
                "ACCESS_CODE must be at least 12 characters -- it is the only "
                "thing protecting the API budget on a public URL"
            )
        return value

    @property
    def uses_placeholder_api_key(self) -> bool:
        return self.anthropic_api_key.get_secret_value() == PLACEHOLDER_API_KEY

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Load and validate settings once.

    Cached because reading and validating on every request is wasted work, and
    because configuration changing mid-process would be a bug, not a feature.
    Tests clear the cache with `get_settings.cache_clear()`.

    Re-raised as ConfigError with a readable message: pydantic's own
    ValidationError is accurate but reads as a wall of JSON pointers, and the
    person hitting this is usually someone setting the project up for the first
    time.
    """
    try:
        settings = Settings()
    except Exception as exc:  # pydantic raises ValidationError; be broad here
        raise ConfigError(_explain(exc)) from exc

    if settings.is_production and settings.uses_placeholder_api_key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is still the placeholder value, and "
            "ENVIRONMENT=production.\n"
            "Set a real key in the host's environment variables."
        )

    return settings


def _explain(exc: Exception) -> str:
    """Turn a validation failure into instructions."""
    missing = []
    other = []
    for error in getattr(exc, "errors", lambda: [])():
        field = ".".join(str(p) for p in error.get("loc", ())) or "(unknown)"
        if error.get("type") == "missing":
            missing.append(field.upper())
        else:
            other.append(f"{field.upper()}: {error.get('msg', '')}")

    if not missing and not other:
        return f"Could not load configuration: {exc}"

    lines = ["Configuration problem -- the server did not start.", ""]
    if missing:
        lines.append("Missing required setting(s): " + ", ".join(missing))
        lines += [
            "",
            "Fix: copy backend/.env.example to backend/.env and fill in the",
            "values. backend/.env is git-ignored, so it will not be committed.",
        ]
    if other:
        if missing:
            lines.append("")
        lines.append("Invalid setting(s):")
        lines += ["  - " + item for item in other]
    return "\n".join(lines)
