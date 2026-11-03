"""The daily ceiling and the rate limiter. Tasks 6.1 and 6.3.

Both classes take their clock as an argument, which is the whole reason this
file can exist: the alternative way to test a rollover at midnight is to wait
until midnight, and the alternative way to test a one-minute window is to sleep
for a minute in a test suite that currently finishes in eight seconds.

The endpoint-level tests at the bottom inject a strict limiter on purpose. The
suite as a whole runs with RATE_LIMIT_PER_MINUTE=600 (see conftest.py) because
dozens of requests from one address would otherwise rate-limit the tests
themselves, which would look like a bug in whichever test ran sixth.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.config import get_settings
from app.limits import DailyBudget, RateLimiter, client_key

client = TestClient(main.app)
CODE = {"X-Access-Code": get_settings().access_code.get_secret_value()}

NOON = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, start: datetime = NOON) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


# --- Task 6.1: the daily ceiling --------------------------------------------


def test_a_fresh_budget_has_its_whole_allowance():
    budget = DailyBudget(limit=15, now=Clock())
    assert budget.limit == 15
    assert budget.used == 0
    assert budget.remaining == 15


def test_reserving_spends_one_slot():
    budget = DailyBudget(limit=3, now=Clock())

    assert budget.reserve() is True
    assert budget.used == 1
    assert budget.remaining == 2


def test_the_cap_is_hard():
    """Task 6.1's "done when", at the unit level: with the cap set to 1, the
    second attempt of the day is refused."""
    budget = DailyBudget(limit=1, now=Clock())

    assert budget.reserve() is True
    assert budget.reserve() is False
    assert budget.remaining == 0
    # And refusing does not quietly increment anything.
    assert budget.used == 1


def test_a_cap_of_zero_refuses_everything():
    """DAILY_SCAN_LIMIT=0 is documented as switching live scanning off, so it
    has to mean zero and not "unlimited", which is the classic way a kill
    switch turns out to be the opposite."""
    budget = DailyBudget(limit=0, now=Clock())

    assert budget.reserve() is False
    assert budget.remaining == 0


def test_the_allowance_comes_back_the_next_day():
    clock = Clock()
    budget = DailyBudget(limit=2, now=clock)
    budget.reserve()
    budget.reserve()
    assert budget.reserve() is False

    clock.advance(hours=13)  # past midnight UTC

    assert budget.remaining == 2
    assert budget.reserve() is True


def test_the_allowance_does_not_come_back_later_the_same_day():
    """Thirteen hours of a long day is not a new day. An hourly reset would
    make the cap meaningless, and a cap that resets more often than it claims
    to is worse than no cap, because it is believed."""
    clock = Clock(datetime(2026, 11, 3, 0, 30, tzinfo=timezone.utc))
    budget = DailyBudget(limit=1, now=clock)
    budget.reserve()

    clock.advance(hours=23)  # 23:30 the same UTC day

    assert budget.reserve() is False


def test_the_day_boundary_is_utc_and_not_local():
    """Midnight UTC, wherever the server happens to be. A local boundary would
    need a timezone setting and would move when the host did."""
    clock = Clock(datetime(2026, 11, 3, 23, 59, 59, tzinfo=timezone.utc))
    budget = DailyBudget(limit=1, now=clock)
    budget.reserve()

    clock.advance(seconds=2)  # 00:00:01 the next day

    assert budget.reserve() is True


# --- Task 6.3: the rate limiter ---------------------------------------------


def test_requests_under_the_limit_are_allowed():
    limiter = RateLimiter(limit=3, window_seconds=60, now=Clock())

    assert limiter.check("1.2.3.4") is None
    assert limiter.check("1.2.3.4") is None
    assert limiter.check("1.2.3.4") is None


def test_the_next_request_over_the_limit_is_refused_with_a_wait():
    limiter = RateLimiter(limit=2, window_seconds=60, now=Clock())
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")

    retry_after = limiter.check("1.2.3.4")

    assert retry_after is not None
    assert 1 <= retry_after <= 61


def test_addresses_are_counted_separately():
    """One person hammering the button must not lock everybody else out."""
    limiter = RateLimiter(limit=1, window_seconds=60, now=Clock())
    limiter.check("1.2.3.4")

    assert limiter.check("1.2.3.4") is not None
    assert limiter.check("5.6.7.8") is None


def test_the_window_expires():
    clock = Clock()
    limiter = RateLimiter(limit=1, window_seconds=60, now=clock)
    limiter.check("1.2.3.4")
    assert limiter.check("1.2.3.4") is not None

    clock.advance(seconds=61)

    assert limiter.check("1.2.3.4") is None


def test_a_refused_request_does_not_extend_the_window():
    """Hammering a locked door should not keep it locked. The wait counts down
    while requests are being refused, rather than restarting on each one."""
    clock = Clock()
    limiter = RateLimiter(limit=1, window_seconds=60, now=clock)
    limiter.check("1.2.3.4")

    clock.advance(seconds=30)
    first_wait = limiter.check("1.2.3.4")
    clock.advance(seconds=20)
    later_wait = limiter.check("1.2.3.4")

    assert later_wait < first_wait


def test_expired_entries_are_swept():
    """The limiter is keyed by address, so without sweeping it grows with
    every new visitor for the life of the process."""
    clock = Clock()
    limiter = RateLimiter(limit=5, window_seconds=60, now=clock)
    for index in range(1_100):
        limiter.check(f"10.0.{index // 256}.{index % 256}")

    clock.advance(seconds=61)
    limiter.check("1.2.3.4")  # a check is what triggers the sweep

    assert len(limiter._windows) < 1_100


# --- Who a request is counted against ---------------------------------------


def fake_request(client_host: str | None, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/scan",
        "headers": headers,
        "client": (client_host, 1234) if client_host else None,
    }
    return Request(scope)


def test_with_no_proxy_the_connection_address_is_used():
    request = fake_request("203.0.113.9", forwarded="1.2.3.4")

    # trusted_proxy_hops=0: there is no proxy, so the header is somebody's
    # invention and the socket is the truth.
    assert client_key(request, trusted_proxy_hops=0) == "203.0.113.9"


def test_behind_one_proxy_the_last_forwarded_entry_wins():
    """The entry a trusted proxy appended, not the one the client claimed.

    This is the whole point. A client sending `X-Forwarded-For: 1.2.3.4` gets
    its real address appended after that by the proxy, so reading from the
    right defeats the spoof, and reading from the left -- the obvious choice --
    would hand out a fresh allowance on every request.
    """
    request = fake_request("10.0.0.1", forwarded="1.2.3.4, 203.0.113.9")

    assert client_key(request, trusted_proxy_hops=1) == "203.0.113.9"


def test_a_spoofed_header_cannot_win():
    limiter = RateLimiter(limit=1, window_seconds=60, now=Clock())
    real = "203.0.113.9"

    for claimed in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        request = fake_request("10.0.0.1", forwarded=f"{claimed}, {real}")
        key = client_key(request, trusted_proxy_hops=1)
        result = limiter.check(key)
        if claimed != "1.1.1.1":
            assert result is not None, "a new claimed address bought a new allowance"


def test_two_proxies_are_counted_from_the_right():
    request = fake_request("10.0.0.1", forwarded="1.2.3.4, 203.0.113.9, 10.0.0.2")

    assert client_key(request, trusted_proxy_hops=2) == "203.0.113.9"


def test_a_missing_forwarded_header_falls_back_to_the_socket():
    request = fake_request("203.0.113.9")

    assert client_key(request, trusted_proxy_hops=1) == "203.0.113.9"


def test_a_request_with_no_peer_address_is_still_counted():
    """Counting these together is the safe direction: one shared bucket, rather
    than every anonymous request being untracked."""
    request = fake_request(None)

    assert client_key(request, trusted_proxy_hops=0) == "unknown"


# --- Through the endpoint ---------------------------------------------------


@pytest.fixture
def strict_limiter(monkeypatch):
    """Two requests a minute, injected for one test."""
    monkeypatch.setattr(main, "rate_limiter", RateLimiter(2, 60, now=Clock()))


def test_too_many_requests_get_the_contract_error(strict_limiter):
    """Task 6.3's "done when": rapid repeat requests get a 429 with a clear
    message. Sent to /verify rather than /scan, so no browser is involved."""
    assert client.post("/verify", headers=CODE).status_code == 200
    assert client.post("/verify", headers=CODE).status_code == 200

    response = client.post("/verify", headers=CODE)

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "rate_limited"
    assert "wait" in body["error"]["message"].lower()
    assert "seconds" in body["error"]["detail"]


def test_the_rate_limit_applies_before_the_access_code(strict_limiter):
    """Order matters: a flood must not even reach the comparison. Three
    requests with no code at all, and the third is refused for being too many
    rather than for being unauthorised."""
    assert client.post("/verify").status_code == 401
    assert client.post("/verify").status_code == 401

    assert client.post("/verify").status_code == 429


@pytest.fixture
def spent_budget(monkeypatch):
    monkeypatch.setattr(main, "daily_budget", DailyBudget(limit=0, now=Clock()))


def test_a_spent_budget_refuses_before_scanning(spent_budget):
    """The first of the contract's two daily_limit_reached cases: the cap was
    already gone, so there is no point starting a four-second scan."""
    response = client.post("/scan", json={"url": "https://example.com"}, headers=CODE)

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "daily_limit_reached"
    assert "resets" in body["error"]["detail"]


def test_the_budget_check_runs_before_the_url_is_resolved(spent_budget):
    """A refused request should not cost a DNS lookup. A blocked URL would
    normally be a 400; past the cap it never gets that far."""
    response = client.post("/scan", json={"url": "http://localhost"}, headers=CODE)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "daily_limit_reached"


def test_health_is_not_rate_limited_or_gated(strict_limiter):
    """The deploy host polls /health, and a host that gets a 429 or a 401 from
    a health check concludes the app is down and restarts it."""
    for _ in range(5):
        assert client.get("/health").status_code == 200


# --- Task 6.1's "done when", through the endpoint ---------------------------


@pytest.fixture
def cap_of_one(monkeypatch):
    """One scan a day, which is what task 6.1 asks to be demonstrated."""
    budget = DailyBudget(limit=1, now=Clock())
    monkeypatch.setattr(main, "daily_budget", budget)
    return budget


def test_the_second_scan_of_the_day_is_refused(cap_of_one, stub_scanner):
    """Task 6.1 verbatim: with the cap set to 1, the second scan of the day
    returns a clear daily-limit result and makes no API call."""
    calls_before = main.explainer.cache.counters.api_calls

    first = client.post("/scan", json={"url": "https://example.com"}, headers=CODE)
    second = client.post("/scan", json={"url": "https://example.com"}, headers=CODE)

    assert first.status_code == 200
    assert first.json()["summary"]["total"] == 2

    assert second.status_code == 429
    body = second.json()
    assert body["error"]["code"] == "daily_limit_reached"
    assert "resets" in body["error"]["detail"]
    assert "today" in body["error"]["message"].lower()

    # "and makes no API call" -- the half of the sentence that is easy to skip.
    assert main.explainer.cache.counters.api_calls == calls_before
    assert cap_of_one.used == 1


def test_a_scan_consumes_exactly_one_slot(cap_of_one, stub_scanner):
    client.post("/scan", json={"url": "https://example.com"}, headers=CODE)

    assert cap_of_one.used == 1
    assert cap_of_one.remaining == 0


def test_a_refused_scan_does_not_consume_a_slot(cap_of_one, stub_scanner):
    """A 429 must not make the hole deeper, or one person refreshing a refused
    page would keep the app locked out for the rest of the day."""
    client.post("/scan", json={"url": "https://example.com"}, headers=CODE)
    for _ in range(5):
        client.post("/scan", json={"url": "https://example.com"}, headers=CODE)

    assert cap_of_one.used == 1


def test_an_unauthorised_request_does_not_consume_a_slot(cap_of_one, stub_scanner):
    """The access code is checked before the ceiling, so somebody without a
    code cannot burn through the allowance."""
    for _ in range(3):
        assert client.post("/scan", json={"url": "https://example.com"}).status_code == 401

    assert cap_of_one.used == 0
    assert client.post(
        "/scan", json={"url": "https://example.com"}, headers=CODE
    ).status_code == 200


def test_a_blocked_url_does_not_consume_a_slot(cap_of_one, stub_scanner):
    """Nothing was scanned, so nothing should have been spent."""
    assert client.post(
        "/scan", json={"url": "http://localhost"}, headers=CODE
    ).status_code == 400

    assert cap_of_one.used == 0


def test_running_out_mid_scan_returns_findings_not_an_error(stub_scanner, monkeypatch):
    """The second of the contract's two `daily_limit_reached` places.

    The allowance is checked before scanning and taken after, so a scan can
    start with room and finish without it -- another request took the last slot
    during the several seconds this one spent loading a page. That is a real
    race, and the contract says it returns 200 with the findings rather than an
    error, because findings without explanations are still worth having.

    Simulated with a budget that passes the up-front check and then refuses,
    which is exactly what the race looks like from inside one request.
    """

    class RaceLostBudget(DailyBudget):
        @property
        def remaining(self) -> int:
            return 1  # looked fine when the request arrived

        def reserve(self) -> bool:
            return False  # gone by the time the scan finished

    monkeypatch.setattr(main, "daily_budget", RaceLostBudget(limit=1, now=Clock()))

    response = client.post("/scan", json={"url": "https://example.com"}, headers=CODE)

    assert response.status_code == 200
    body = response.json()
    assert body["explanations_available"] is False
    assert body["explanations_unavailable_reason"] == "daily_limit_reached"
    assert body["summary"]["total"] == 2
    assert len(body["issues"]) == 2
    assert all(issue["explanation"] is None for issue in body["issues"])
    assert all(issue["fix"] is None for issue in body["issues"])


def test_tomorrow_the_app_works_again(cap_of_one, stub_scanner, monkeypatch):
    """The cap has to be a daily cap and not a lifetime one, which is only
    testable at all because the clock is injected."""
    clock = Clock()
    budget = DailyBudget(limit=1, now=clock)
    monkeypatch.setattr(main, "daily_budget", budget)

    assert client.post("/scan", json={"url": "https://example.com"}, headers=CODE).status_code == 200
    assert client.post("/scan", json={"url": "https://example.com"}, headers=CODE).status_code == 429

    clock.advance(hours=13)  # past midnight UTC

    assert client.post("/scan", json={"url": "https://example.com"}, headers=CODE).status_code == 200


def test_scan_is_rate_limited_before_the_access_code_is_checked(strict_limiter):
    """The same ordering as /verify, asserted on /scan too.

    These are two separate dependency lists, so testing one proves nothing
    about the other -- which a deliberate mutation of /scan's order went on to
    demonstrate by passing every test in this file.

    Order matters here because the comparison is the expensive, attackable
    part: a flood of guesses should run out of requests before it runs out of
    anything else.
    """
    assert client.post("/scan", json={"url": "https://example.com"}).status_code == 401
    assert client.post("/scan", json={"url": "https://example.com"}).status_code == 401

    third = client.post("/scan", json={"url": "https://example.com"})

    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"


def test_the_refusal_carries_a_retry_after_header(strict_limiter):
    """The body says how long to wait in words; this is the version a client
    obeys without anybody reading it. The two have to agree."""
    client.post("/verify", headers=CODE)
    client.post("/verify", headers=CODE)

    response = client.post("/verify", headers=CODE)

    assert response.status_code == 429
    assert "retry-after" in response.headers
    seconds = int(response.headers["retry-after"])
    assert 1 <= seconds <= 61
    assert str(seconds) in response.json()["error"]["detail"]


def test_a_cap_of_one_says_scan_and_not_scans(stub_scanner, monkeypatch):
    """Small thing, but this string is read by whoever hits the limit."""
    monkeypatch.setattr(main, "daily_budget", DailyBudget(limit=1, now=Clock()))
    client.post("/scan", json={"url": "https://example.com"}, headers=CODE)

    detail = client.post(
        "/scan", json={"url": "https://example.com"}, headers=CODE
    ).json()["error"]["detail"]

    assert "1 scan has been used" in detail


def test_other_errors_carry_no_stray_headers():
    """`headers` is optional on ApiError, and an error that does not set it
    must not acquire one."""
    response = client.post("/verify")

    assert response.status_code == 401
    assert "retry-after" not in response.headers
