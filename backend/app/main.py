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

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.requests import Request

from app.auth import AccessCode
from app.config import ConfigError, get_settings
from app.errors import ApiError, register_error_handlers, register_request_logging
from app.explainer import UNAVAILABLE_LIMIT, Explainer, mark_unavailable
from app.limits import DailyBudget, RateLimiter, client_key
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

# The same logger name every other module uses, so one configuration covers
# the lot and a filter applied to "a11y_lens" catches everything.
logger = logging.getLogger("a11y_lens")

# --- Task 4.6: one browser for the whole server -----------------------------
#
# Started before the first request and stopped on the way out, rather than
# launched per scan. Phase 1 measured Chromium's floor at about 321MB and
# several seconds, so per-request launching would make every scan pay a cost
# that only needs paying once.
scanner = Scanner()

# --- Task 5.6: the explanation client ---------------------------------------
#
# Same lifetime as the browser and for a smaller version of the same reason:
# one client, pooling its connections, rather than one per request. It also
# holds the explanation cache, which is only worth anything if it survives
# between requests.
#
# `enabled` is what makes a fresh clone work with no API key at all: the
# explainer then makes no calls and every scan returns the contract's degraded
# success instead of failing.
explainer = Explainer(
    api_key=settings.anthropic_api_key.get_secret_value(),
    model=settings.anthropic_model,
    effort=settings.anthropic_effort,
    timeout_ms=settings.explain_timeout_ms,
    enabled=not settings.uses_placeholder_api_key,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Everything before `yield` runs at startup, everything after at shutdown.

    The browser is started eagerly rather than on the first scan, so that the
    first person to use the app does not wait for Chromium on top of their
    own scan. The cost is paid while the deploy host is still warming up.
    """
    await scanner.start()
    try:
        await explainer.start()
        try:
            yield
        finally:
            await explainer.stop()
    finally:
        # In a finally, so a crash during shutdown still does not leave a
        # Chromium process behind. Nested rather than side by side so that a
        # failure stopping one still stops the other.
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


# --- Phase 6: the gate and the ceiling --------------------------------------
#
# Three checks, and the order they run in is the design. Cheapest and most
# protective first:
#
#   1. rate limit -- counted per address, so a flood cannot even reach the
#      access code check, let alone a DNS lookup or a browser.
#   2. access code -- a timing-safe comparison, and the front door: the app is
#      link-only, so there is nothing to see without it.
#   3. daily ceiling -- checked here, but *taken* inside the explainer, at the
#      moment money is about to be spent. A cached page costs nothing.
#   4. URL safety -- last of the checks, because it resolves DNS. Real work is
#      not worth doing for a request that was never allowed.
require_access_code = AccessCode(settings.access_code.get_secret_value())
daily_budget = DailyBudget(settings.daily_scan_limit)
rate_limiter = RateLimiter(settings.rate_limit_per_minute, window_seconds=60)


def enforce_rate_limit(request: Request) -> None:
    """Refuse an address that is asking too often, and say for how long."""
    retry_after = rate_limiter.check(client_key(request, settings.trusted_proxy_hops))
    if retry_after is None:
        return
    # The address is deliberately not logged: it is the one piece of personal
    # data this app handles, and "somebody was rate limited" is the whole of
    # what is useful here.
    logger.info("a request was rate limited; retry after %ds", retry_after)
    raise ApiError(
        "rate_limited",
        detail=f"Wait {retry_after} seconds and try again.",
        # The standard header, so a client can back off without anybody
        # reading the sentence above.
        headers={"Retry-After": str(retry_after)},
    )


def require_daily_budget() -> None:
    """Refuse before scanning if today's allowance is already gone.

    This is the first of the two places `docs/api-contract.md` puts
    `daily_limit_reached`: the cap was already reached, so there is no point
    starting a four-second scan whose explanations could never be written. The
    second place is inside the explainer, for the allowance running out while
    this request was busy.
    """
    if daily_budget.remaining <= 0:
        scans = "scan" if daily_budget.limit == 1 else "scans"
        raise ApiError(
            "daily_limit_reached",
            detail=f"Today's limit of {daily_budget.limit} {scans} has been "
                   "used. It resets at midnight UTC.",
        )


@app.post("/verify", dependencies=[Depends(enforce_rate_limit)])
def verify(_: None = Depends(require_access_code)) -> dict[str, bool]:
    """Is this access code right? Nothing else.

    The frontend's code screen (task 8.0) calls this once on load. It exists
    because the alternative -- asking `/scan` and seeing whether it refuses --
    would run a real scan and spend a real slot just to check a password.

    No browser, no Claude, no budget. A wrong code is the same `unauthorized`
    error shape as everywhere else, and the rate limiter applies so this cannot
    be used to guess the code quickly.
    """
    return {"ok": True}


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


@app.post(
    "/scan",
    response_model=Report,
    dependencies=[
        Depends(enforce_rate_limit),
        Depends(require_access_code),
        Depends(require_daily_budget),
    ],
)
async def scan(request: ScanRequest) -> Report:
    """Scan one page and return its accessibility report.

    The order here is the whole point of Phase 3: **nothing is fetched until
    check_url has approved the address.** A URL pointing inside a private
    network is refused here, before a browser is ever asked to open it.

    check_url resolves DNS, which blocks, so it runs in a worker thread rather
    than on the event loop that is also driving the browser.

    The explanation step comes second and cannot fail the request: by the time
    it runs there is already a complete, valid report, and `explain` returns
    that report marked as degraded rather than raising. A scan that found ten
    real problems is worth having even when Claude is down.

    No access code yet -- task 6.2 adds that, and task 6.1 adds the daily
    ceiling. This endpoint must not be reachable from the internet until both
    exist, which is why Phase 6 says so in capital letters.
    """
    safe_url = await asyncio.to_thread(check_url, request.url)
    report = await scanner.scan(safe_url, settings.scan_timeout_ms)

    # The slot is taken here, after the scan and before the explanation.
    #
    # Not before the scan, because `require_daily_budget` has already refused
    # the easy case and a slot held across four seconds of page loading would
    # be lost entirely if the scan then failed. Not inside the explainer,
    # because the ceiling counts scans -- it protects the host's memory as
    # well as the API budget, and with no API key configured there would
    # otherwise be no ceiling on scanning at all.
    #
    # This is the second of the two places docs/api-contract.md puts
    # `daily_limit_reached`: the allowance ran out while this scan was running,
    # which is a real race rather than a theoretical one, because a scan holds
    # things up for several seconds.
    if not daily_budget.reserve():
        logger.warning(
            "the daily allowance ran out while a scan was running; "
            "returning findings without explanations"
        )
        return mark_unavailable(report, UNAVAILABLE_LIMIT)

    return await explainer.explain(report)
