"""The FastAPI application.

Phase 2 complete: the health check, configuration validated at startup, CORS,
and one error shape for every failure.

Phase 4 added the scan endpoint, which is the thing the app is actually for.
It is also where `app.url_safety` is applied: once, on the way in, to
everything that comes from outside.

The health check was built first because every later task needs a way to ask
"is the server up?" that does not depend on anything else working.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import ConfigError, get_settings
from app.errors import register_error_handlers, register_request_logging
from app.scanner import Report, Scanner
from app.url_safety import MAX_URL_LENGTH, check_url

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

# --- Task 4.6: one browser for the whole server -----------------------------
#
# Started before the first request and stopped on the way out, rather than
# launched per scan. Phase 1 measured Chromium's floor at about 321MB and
# several seconds, so per-request launching would make every scan pay a cost
# that only needs paying once.
scanner = Scanner()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Everything before `yield` runs at startup, everything after at shutdown.

    The browser is started eagerly rather than on the first scan, so that the
    first person to use the app does not wait for Chromium on top of their
    own scan. The cost is paid while the deploy host is still warming up.
    """
    await scanner.start()
    try:
        yield
    finally:
        # In a finally, so a crash during shutdown still does not leave a
        # Chromium process behind.
        await scanner.stop()


app = FastAPI(
    title="A11y-Lens API",
    version=API_VERSION,
    description="Scans a web page for accessibility issues and explains them.",
    lifespan=lifespan,
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


# --- Task 4.7: the scan endpoint --------------------------------------------


class ScanRequest(BaseModel):
    """The request body, which docs/api-contract.md section 2 defines as
    exactly one field.

    A body that does not match this produces a RequestValidationError, which
    app.errors maps to `invalid_url` -- so a missing or mistyped field comes
    back in the same shape as every other failure.
    """

    url: str = Field(
        ...,
        max_length=MAX_URL_LENGTH,
        description="The page to scan. Must be http or https and publicly reachable.",
    )


@app.post("/scan", response_model=Report)
async def scan(request: ScanRequest) -> Report:
    """Scan one page and return its accessibility report.

    The order here is the whole point of Phase 3: **nothing is fetched until
    check_url has approved the address.** A URL pointing inside a private
    network is refused here, before a browser is ever asked to open it.

    check_url resolves DNS, which blocks, so it runs in a worker thread rather
    than on the event loop that is also driving the browser.

    No access code yet -- task 6.2 adds that, and task 6.1 adds the daily
    ceiling. This endpoint must not be reachable from the internet until both
    exist, which is why Phase 6 says so in capital letters.
    """
    safe_url = await asyncio.to_thread(check_url, request.url)
    return await scanner.scan(safe_url, settings.scan_timeout_ms)
