"""The access code. Task 6.2.

One shared secret, from the environment, checked on every route that can spend
money or do work. It is the front door: the app is link-only, so there is no
public page behind it and nothing renders without a valid code.

Three things this file is careful about.

**The comparison is timing-safe.** `==` on strings stops at the first byte that
differs, so how long a wrong answer takes to reject leaks how much of it was
right -- enough, over many attempts, to recover a secret a character at a time.
`secrets.compare_digest` takes the same time either way. The rate limiter makes
that attack slow as well, but defence in depth costs one import here.

**The code never appears in a log, a message or a response.** Not the expected
one, and not the one that was offered either: a mistyped code in a log file is
still somebody's secret, and a near-miss would be a hint. `app.errors` already
declines to log request headers for this reason.

**It travels in a header, never the URL.** `docs/api-contract.md` fixes this:
URLs end up in browser history, server logs and `Referer` headers, and a secret
in a URL is a secret in several places nobody is thinking about.
"""

import logging
import secrets
from typing import Annotated

from fastapi import Header

from app.errors import ApiError

logger = logging.getLogger("a11y_lens")

HEADER_NAME = "X-Access-Code"


class AccessCode:
    """A FastAPI dependency that refuses requests without the shared code.

    An instance rather than a plain function so the expected code is passed in
    rather than read from configuration here -- which is what lets a test build
    one with a known code, and keeps this module free of any opinion about
    where settings come from.
    """

    def __init__(self, expected: str) -> None:
        if not expected:
            # Should be unreachable: config.py requires ACCESS_CODE and refuses
            # anything under 12 characters. Checked anyway, because the failure
            # mode of an empty expected code is an app that looks protected and
            # accepts everything.
            raise ValueError("the expected access code must not be empty")
        self._expected = expected.encode("utf-8")

    def __call__(
        self,
        x_access_code: Annotated[str | None, Header()] = None,
    ) -> None:
        """Raises `unauthorized` (401) unless the header matches exactly.

        FastAPI maps the parameter name to the header name, so
        `x_access_code` is `X-Access-Code`. Returns nothing: a dependency that
        either passes or raises reads better at the call site than one whose
        return value has to be checked.
        """
        if x_access_code is None:
            # A missing header is not a guess at the secret, so there is
            # nothing to compare and no timing to equalise.
            raise ApiError("unauthorized", detail=f"Send the code in the {HEADER_NAME} header.")

        if not secrets.compare_digest(x_access_code.encode("utf-8"), self._expected):
            # Deliberately says nothing about *how* it was wrong, and logs
            # neither the offered code nor its length.
            logger.warning("a request was refused: the access code did not match")
            raise ApiError("unauthorized", detail="That access code is not right.")
