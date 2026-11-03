"""The two limits that stand between a forwarded link and an empty account.

Phase 6. Tasks 6.1 and 6.3.

**The daily budget is the one that matters.** The access code is obscurity --
links get forwarded, pasted into chat and screenshotted -- so the only thing
that actually bounds the damage is a hard ceiling on how many times a day this
app is willing to spend money. Rate limiting is a third line, and a modest one.

Both live in memory, in dictionaries, and both forget everything when the
process restarts. That is a deliberate trade and worth being clear about:

- A dictionary costs nothing, needs no database, cannot be misconfigured, and
  on a budget of zero that matters more than durability.
- The cost is that a restart resets both counters. A host that restarts the
  app every hour would hand out a fresh allowance every hour. Free tiers do
  restart, so the ceiling is a brake and not a guarantee.
- **The deploy must run a single worker.** Two uvicorn workers mean two
  processes, two dictionaries and two independent allowances, so the real cap
  would quietly be double what is configured. A scan peaks near 859MB, so one
  worker is required on a small host anyway -- but it has to be checked rather
  than assumed, which is a Phase 10 job.

Neither class uses a lock. Both are only ever touched from the event loop, and
neither has an `await` between reading a counter and writing it, so there is no
point at which another request can interleave. That is a property of how they
are written, not a happy accident, so it is worth not breaking.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timezone

from starlette.requests import Request

logger = logging.getLogger("a11y_lens")

# Above this many tracked addresses, expired entries are swept. A dictionary
# keyed by client address grows with every new visitor and would otherwise be
# a slow memory leak on a long-running process.
RATE_LIMIT_SWEEP_AT = 1_024


def utc_now() -> datetime:
    """The clock, as a function so tests can replace it.

    Injected rather than called directly because the alternative way to test a
    rollover at midnight is to wait until midnight.
    """
    return datetime.now(timezone.utc)


class DailyBudget:
    """A hard ceiling on how many scans this app performs in a day.

    **Counts scans, not Claude calls.** That is what `DAILY_SCAN_LIMIT` has
    always claimed to be, and it is the more useful of the two: a scan costs
    money *and* costs the host nearly 859MB and several seconds, so counting
    API calls would leave scanning uncapped whenever no API key is configured.

    The slot is taken once per scan, after the page has been loaded and before
    the explanation -- see `app.main`. A page whose explanations come straight
    from the cache still consumes a slot, because the scan itself was the
    expensive part; what the cache saves is the money, not the allowance.

    The day is UTC. A local day boundary would need a timezone setting, and the
    only question this has to answer is "has it rolled over", which UTC answers
    the same way everywhere.
    """

    def __init__(self, limit: int, now: Callable[[], datetime] = utc_now) -> None:
        self._limit = limit
        self._now = now
        self._day: date = now().date()
        self._used = 0

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def used(self) -> int:
        self._roll_over()
        return self._used

    @property
    def remaining(self) -> int:
        self._roll_over()
        return max(0, self._limit - self._used)

    def _roll_over(self) -> None:
        today = self._now().date()
        if today != self._day:
            logger.info(
                "daily budget reset: %d of %d used on %s",
                self._used,
                self._limit,
                self._day.isoformat(),
            )
            self._day = today
            self._used = 0

    def reserve(self) -> bool:
        """Take one slot if there is one. True means go ahead and spend.

        Called immediately before the API request, never earlier. Reserving at
        the start of a scan instead would mean a slot held for the four seconds
        a page takes to load, and lost entirely if the scan then failed.
        """
        self._roll_over()
        if self._used >= self._limit:
            return False
        self._used += 1
        if self.remaining == 0:
            logger.warning(
                "daily budget exhausted: %d of %d used; explanations are off "
                "until tomorrow",
                self._used,
                self._limit,
            )
        return True


class RateLimiter:
    """A modest per-address limit, in a fixed window.

    Fixed window rather than a sliding one or a token bucket: it is a handful
    of lines, it cannot drift, and the thing it defends against here is a
    person holding down a button or a script in a loop -- not a distributed
    attack. A sliding window would be more correct at the window edges and
    would buy nothing a shared link needs.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._now = now
        # address -> (window started at, requests so far in that window)
        self._windows: dict[str, tuple[datetime, int]] = {}

    def check(self, key: str) -> int | None:
        """Count one request. Returns seconds to wait if it is over the limit.

        `None` means allowed. A number means refused, and it is what goes in
        the `Retry-After` header -- the contract says this error has to convey
        how long to wait, and a number is the only honest way to do that.
        """
        now = self._now()
        started, count = self._windows.get(key, (now, 0))
        age = (now - started).total_seconds()

        if age >= self._window:
            started, count = now, 0

        if count >= self._limit:
            return max(1, int(self._window - age) + 1)

        self._windows[key] = (started, count + 1)
        if len(self._windows) > RATE_LIMIT_SWEEP_AT:
            self._sweep(now)
        return None

    def _sweep(self, now: datetime) -> None:
        stale = [
            key
            for key, (started, _) in self._windows.items()
            if (now - started).total_seconds() >= self._window
        ]
        for key in stale:
            del self._windows[key]
        logger.info("rate limiter swept %d expired entries", len(stale))


def client_key(request: Request, trusted_proxy_hops: int) -> str:
    """Which address to count a request against.

    Behind a proxy, the connection comes from the proxy and the real address is
    in `X-Forwarded-For`. That header is also attacker-controlled, so reading
    the first entry -- the obvious choice, and the usual mistake -- lets anyone
    send `X-Forwarded-For: 1.2.3.4` and get a fresh allowance per request,
    which defeats the whole purpose.

    Each proxy *appends* the address it received the request from, so the
    trustworthy entries are at the **end**. With one trusted proxy in front of
    us, the last entry was written by that proxy and is the real client, no
    matter what the client claimed. Hence counting from the right.

    `trusted_proxy_hops` is 0 in local development, where there is no proxy and
    the connection address is the truth. It must be set to the real number in
    production: too low and a spoofed header wins, too high and every request
    looks like it came from the same made-up address.
    """
    if trusted_proxy_hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            if hops:
                index = max(0, len(hops) - trusted_proxy_hops)
                return hops[index]

    if request.client is None:
        # No peer address at all. Counting these together is the safe
        # direction: it rate-limits them as one caller rather than letting
        # each be untracked.
        return "unknown"
    return request.client.host
