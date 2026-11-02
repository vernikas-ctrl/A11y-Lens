"""One error shape for every failure, at every status code.

Task 2.5, implementing section 3 of docs/api-contract.md.

Every error response from this API looks like this and nothing else:

    {"error": {"code": "...", "message": "...", "detail": "..." | null}}

Why it matters enough to centralise:

- **The frontend branches on `code`, never on `message`.** Codes are a stable
  contract; messages get reworded. If some failures came back as FastAPI's
  `{"detail": "Not Found"}` and others as our shape, the frontend would need
  two parsers and would get the second one wrong.
- **`message` is shown to the user as-is**, so it is written in plain language
  and says what to do next, not what went wrong internally.
- **`detail` never carries anything an attacker could use.** For unexpected
  failures it is `null` and the real cause goes to the server log instead.
"""

import logging
import time
import uuid
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("a11y_lens")

ErrorCode = Literal[
    "invalid_url",
    "blocked_address",
    "unauthorized",
    "not_found",
    "method_not_allowed",
    "rate_limited",
    "daily_limit_reached",
    "unreachable",
    "scan_timeout",
    "internal_error",
]

# The single source of truth for which status each code returns. Deriving the
# status from the code makes the pair impossible to get out of step -- the
# alternative is passing both at every raise site and eventually mismatching
# them.
STATUS_FOR_CODE: dict[str, int] = {
    "invalid_url": 400,
    "blocked_address": 400,
    "unauthorized": 401,
    "not_found": 404,
    "method_not_allowed": 405,
    "rate_limited": 429,
    "daily_limit_reached": 429,
    "internal_error": 500,
    "unreachable": 502,
    "scan_timeout": 504,
}

# Used when something raises a bare HTTPException: map its status onto the
# nearest contract code rather than inventing a new shape.
CODE_FOR_STATUS: dict[int, str] = {
    400: "invalid_url",
    401: "unauthorized",
    404: "not_found",
    405: "method_not_allowed",
    429: "rate_limited",
    502: "unreachable",
    504: "scan_timeout",
}

# Default user-facing wording per code. Plain language, and each says what to
# do next rather than merely naming the failure.
DEFAULT_MESSAGE: dict[str, str] = {
    "invalid_url": (
        "That does not look like a web address. Enter a full URL starting "
        "with http:// or https://."
    ),
    "blocked_address": (
        "That address points inside a private network, so A11y-Lens will not "
        "scan it. This is deliberate, not a fault."
    ),
    "unauthorized": (
        "Live scanning needs an access code. The demo report is available "
        "without one."
    ),
    "not_found": "There is nothing at that address on this API.",
    "method_not_allowed": "That address does not accept this kind of request.",
    "rate_limited": "Too many scans from this address. Wait a minute and try again.",
    "daily_limit_reached": (
        "A11y-Lens has reached its scan limit for today. It resets tomorrow."
    ),
    "unreachable": (
        "That page could not be reached. Check the address is right and that "
        "the site is up — the problem is with the page, not with A11y-Lens."
    ),
    "scan_timeout": (
        "That page took too long to load. It may be unusually slow; it is "
        "worth trying again."
    ),
    "internal_error": "Something went wrong on our side. Sorry about that.",
}


class ApiError(Exception):
    """Raise this anywhere to produce a contract-shaped error response.

    Status code is derived from `code`, so a raise site cannot pair them wrong.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        detail: str | None = None,
    ) -> None:
        if code not in STATUS_FOR_CODE:
            # A typo in a code would otherwise reach the frontend, which
            # branches on it, and silently match none of its cases.
            raise ValueError(f"unknown error code: {code!r}")
        self.code = code
        self.message = message or DEFAULT_MESSAGE[code]
        self.detail = detail
        self.status_code = STATUS_FOR_CODE[code]
        super().__init__(self.message)


def error_response(
    code: str,
    message: str | None = None,
    detail: str | None = None,
) -> JSONResponse:
    """Build the response body. The only place this shape is constructed."""
    return JSONResponse(
        status_code=STATUS_FOR_CODE.get(code, 500),
        content={
            "error": {
                "code": code,
                "message": message or DEFAULT_MESSAGE.get(code, ""),
                "detail": detail,
            }
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach handlers so no failure escapes in another shape."""

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Covers FastAPI's own 404s and 405s.

        This is the handler the task's "Done when" is about: without it, a
        request to an unknown route returns {"detail": "Not Found"}, which is
        not the contract shape.
        """
        code = CODE_FOR_STATUS.get(exc.status_code, "internal_error")
        return error_response(code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """A malformed request body.

        Mapped to invalid_url rather than a 422: the contract lists no 422, and
        the only request body in this API is {"url": ...}, so a validation
        failure is a bad URL by definition. The specific field goes in detail,
        which is safe -- it describes the request the caller just sent.
        """
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', ()) if p != 'body')}: "
            f"{err.get('msg', '')}"
            for err in exc.errors()
        )
        return error_response("invalid_url", detail=problems or None)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """The catch-all.

        `detail` is deliberately null. An exception message can contain file
        paths, query fragments or key material, and this response goes to a
        stranger on the internet. The real cause is logged instead, with an id
        the log and the response share so a report can be traced.

        Returning a response rather than re-raising also keeps the CORS headers
        on it: an exception that escapes the middleware stack arrives at the
        browser as an opaque CORS failure instead of a readable 500.
        """
        incident = uuid.uuid4().hex[:12]
        logger.exception(
            "unhandled error %s on %s %s",
            incident,
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return error_response(
            "internal_error",
            detail=f"Reference {incident}",
        )


def register_request_logging(app: FastAPI) -> None:
    """Log one line per request: method, path, status, duration.

    Deliberately not the headers. `X-Access-Code` travels in a header, and the
    fastest way to leak a secret is to log every request's headers "just for
    debugging" and forget. The query string is omitted for the same reason.
    """

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.info(
            "%s %s -> %s (%dms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
