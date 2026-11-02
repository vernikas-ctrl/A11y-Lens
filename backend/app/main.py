"""The FastAPI application.

Tasks 2.1 and 2.3 so far: the health check, and configuration validated at
startup. Still to come: CORS in 2.4, the shared error shape in 2.5, URL safety
in Phase 3, and the scan endpoint in Phase 4.

The health check was built first because every later task needs a way to ask
"is the server up?" that does not depend on anything else working.
"""

import sys

from fastapi import FastAPI

from app.config import ConfigError, get_settings

# Validated at import, before a single request is served. A configuration
# mistake should stop the server immediately with an explanation, not surface
# as a confusing 500 on the first scan an hour later.
#
# SystemExit rather than letting the exception propagate: uvicorn would print a
# traceback, and the person who sees this is usually setting the project up for
# the first time. They need the instructions, not the call stack.
try:
    settings = get_settings()
except ConfigError as exc:
    print(f"\n{exc}\n", file=sys.stderr)
    raise SystemExit(1) from exc

# Bumped by hand when the response shape changes, so a deployed frontend can
# tell which backend it is talking to. Not the git tag and not read from the
# package metadata -- this is the API's version, not the project's.
API_VERSION = "0.1.0"

if settings.uses_placeholder_api_key:
    # Not fatal in development: Phases 2-4 never call Claude, so there is no
    # reason to block local work on a key that is not needed yet. Phase 5 is
    # where it starts to matter, and production refuses to start without it.
    print(
        "WARNING: ANTHROPIC_API_KEY is still the placeholder value. "
        "Scanning will work; explanations will not.",
        file=sys.stderr,
    )

app = FastAPI(
    title="A11y-Lens API",
    version=API_VERSION,
    description="Scans a web page for accessibility issues and explains them.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check.

    Deliberately does no work: it must answer even when the browser, the Claude
    API or anything else is broken, because its job is to distinguish "the
    server is down" from "the server is up and something else is wrong".

    No authentication, by the contract in docs/api-contract.md -- the deploy
    host has to be able to call it, and it reveals nothing.
    """
    return {"status": "ok", "version": API_VERSION}
