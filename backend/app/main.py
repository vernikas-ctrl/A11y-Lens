"""The FastAPI application.

Phase 2 complete: the health check, configuration validated at startup, CORS,
and one error shape for every failure. Still to come: URL safety in Phase 3,
and the scan endpoint in Phase 4.

The health check was built first because every later task needs a way to ask
"is the server up?" that does not depend on anything else working.
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ConfigError, get_settings
from app.errors import register_error_handlers, register_request_logging

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

# uvicorn configures its own loggers but not ours, so without this the request
# log and the error log would go nowhere when running under uvicorn.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="A11y-Lens API",
    version=API_VERSION,
    description="Scans a web page for accessibility issues and explains them.",
)

# --- Task 2.5: one error shape, and request logging -------------------------
#
# Registered before anything that can fail, so there is no window in which a
# route returns FastAPI's default error body instead of the contract's.
register_error_handlers(app)
register_request_logging(app)

# --- Task 2.4: CORS ---------------------------------------------------------
#
# A browser will not let a page on one origin read a response from another
# unless the response says it may. The frontend runs on localhost:5173 in
# development and on Vercel in production, while the API is somewhere else
# entirely, so without this the frontend gets an opaque network error with
# nothing useful in it.
#
# The origin list comes from configuration, never from a literal here: task
# 10.4 narrows it to the real Vercel domain, and that must be a deploy-time
# change, not a code change.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    # Named explicitly rather than ["*"]. A wildcard would also permit methods
    # this API does not have, and the error for calling one should be a clean
    # 405 from us rather than a confusing CORS failure in the console.
    allow_methods=["GET", "POST", "OPTIONS"],
    # X-Access-Code is the header the contract puts the shared code in. Without
    # it listed here the browser blocks the request before it is ever sent,
    # which looks like the server being down.
    allow_headers=["Content-Type", "X-Access-Code"],
    # No cookies and no HTTP auth: access is a header the frontend sets itself.
    # Leaving this False also means allow_origins can never be combined with
    # credentials by accident, which is the classic CORS hole.
    allow_credentials=False,
    max_age=600,
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
