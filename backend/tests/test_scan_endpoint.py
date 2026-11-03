"""Tasks 4.4, 4.6 and 4.7 -- the endpoint, browser reuse, and every failure.

Three kinds of test, for three different reasons:

- **Endpoint tests with no browser at all.** The app's lifespan is what starts
  Chromium, and a plain `TestClient(app)` does not run it. That is useful
  rather than awkward: if a request that should have been refused ever reached
  the scanner, it would fail with ScannerNotStarted and a 500 instead of the
  400 these tests assert. So a passing test here is positive evidence that the
  safety check ran *first*.
- **One real browser session**, started once for the whole module, doing every
  piece of work that needs a live Chromium. Same reasoning as test_scanner.py:
  the browser is the expensive part.
- **Failure mapping against fakes.** A page that times out, a domain that does
  not resolve and a server returning 500 are all awkward to arrange for real
  and trivial to describe exactly. The logic being tested is the mapping from
  Chromium's errors to the contract's codes, and a fake exercises that
  directly.
"""

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app import main
from app.config import get_settings
from app.errors import ApiError
from app.main import app
from app.scanner import (
    Report,
    Scanner,
    ScannerNotStarted,
    _block_requests_to_private_addresses,
    _goto,
    _reject_unsuccessful_response,
)

FIXTURE = Path(__file__).parent / "fixtures" / "broken.html"

# No `with`, so no lifespan, so no browser. See the module docstring.
client = TestClient(app)

# Phase 6 put an access code in front of /scan, so every request here carries
# one. Read from configuration rather than written out, so there is exactly one
# place the test code lives (tests/conftest.py) and no literal to drift.
CODE = {"X-Access-Code": get_settings().access_code.get_secret_value()}


# --- Task 4.7: the safety check runs before anything is fetched -------------

REFUSED_BY_URL_SAFETY = [
    pytest.param("http://localhost:8000/health", "blocked_address", id="localhost"),
    pytest.param("http://127.0.0.1/", "blocked_address", id="loopback"),
    pytest.param("http://169.254.169.254/", "blocked_address", id="cloud-metadata"),
    pytest.param("http://10.0.0.1/", "blocked_address", id="private-network"),
    pytest.param("file:///etc/passwd", "invalid_url", id="file-scheme"),
    pytest.param("javascript:alert(1)", "invalid_url", id="javascript-scheme"),
    pytest.param("not a url", "invalid_url", id="prose"),
    pytest.param("", "invalid_url", id="empty"),
]


@pytest.mark.parametrize("url,expected_code", REFUSED_BY_URL_SAFETY)
def test_the_safety_check_runs_before_the_browser(url, expected_code):
    """Task 4.7's "Done when", and the guard named in DECISIONS.md.

    The scanner deliberately does not check its own URLs, which is only safe
    while the endpoint does. This is the test that keeps that true.

    It is also why there is no browser running: reaching the scanner at all
    would produce a 500, not the 400 asserted here.
    """
    response = client.post("/scan", json={"url": url}, headers=CODE)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == expected_code


MALFORMED_BODIES = [
    pytest.param({}, id="no-url-field"),
    pytest.param({"url": None}, id="null-url"),
    pytest.param({"url": 42}, id="url-is-a-number"),
    pytest.param({"address": "https://example.com"}, id="wrong-field-name"),
    pytest.param({"url": "https://example.com/" + "x" * 3000}, id="absurdly-long"),
]


@pytest.mark.parametrize("body", MALFORMED_BODIES)
def test_a_malformed_body_still_comes_back_in_the_contract_shape(body):
    """FastAPI answers a bad body with a 422 and its own format by default.
    app.errors maps it to invalid_url, so the frontend has one parser."""
    response = client.post("/scan", json=body, headers=CODE)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_url"
    assert set(error) == {"code", "message", "detail"}


def test_scan_is_a_post_only_route():
    response = client.get("/scan")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


# --- One real browser, doing everything that needs one ----------------------


@pytest.fixture(scope="module")
def browser_work() -> dict:
    """Start one browser, do every job that needs it, hand back plain data.

    Deliberately one fixture doing several things. Starting Chromium is the
    expensive part, and a Playwright browser belongs to the event loop that
    created it -- so it cannot be held across separate `asyncio.run()` calls.
    Everything that needs the live browser therefore happens inside this one
    coroutine, and the tests below assert on what it returns.
    """

    async def main() -> dict:
        scanner = Scanner()
        results: dict = {"running_before_start": scanner.is_running}

        await scanner.start()
        results["running_after_start"] = scanner.is_running
        results["browser_before"] = id(scanner._browser)

        try:
            page_url = FIXTURE.resolve().as_uri()

            first_started = time.monotonic()
            results["first"] = await scanner.scan(page_url, timeout_ms=30_000)
            results["first_elapsed"] = time.monotonic() - first_started

            second_started = time.monotonic()
            results["second"] = await scanner.scan(page_url, timeout_ms=30_000)
            results["second_elapsed"] = time.monotonic() - second_started

            # The same browser object throughout, or it was relaunched.
            results["browser_after"] = id(scanner._browser)

            # A page that is not there. Chromium refuses it, which is the
            # `unreachable` path, arranged without a network.
            missing = (FIXTURE.parent / "no-such-page.html").resolve().as_uri()
            try:
                await scanner.scan(missing, timeout_ms=30_000)
            except ApiError as exc:
                results["missing_page_error"] = exc
        finally:
            await scanner.stop()

        # What a scan would cost with no browser already running -- which is
        # what every scan would cost without task 4.6. Measured rather than
        # assumed, because it is the only honest comparison: two scans on an
        # already-warm browser take about the same time as each other.
        cold = Scanner()
        cold_started = time.monotonic()
        await cold.start()
        await cold.scan(page_url, timeout_ms=30_000)
        results["cold_elapsed"] = time.monotonic() - cold_started
        await cold.stop()

        results["running_after_stop"] = scanner.is_running
        return results

    return asyncio.run(main())


def test_the_report_matches_the_contract(browser_work):
    """docs/api-contract.md sections 2.1 and 2.3, field by field."""
    report = browser_work["first"]

    assert set(report) == {
        "url", "page_title", "scanned_at", "scan_duration_ms",
        "explanations_available", "explanations_unavailable_reason",
        "summary", "issues",
    }
    assert report["page_title"] == "A deliberately broken page"
    assert report["scanned_at"].endswith("Z")
    assert report["scan_duration_ms"] > 0
    assert set(report["summary"]) == {
        "critical", "serious", "moderate", "minor", "total"
    }
    assert report["summary"]["total"] == len(report["issues"])


def test_the_report_says_explanations_are_missing_and_why(browser_work):
    """Contract section 2.3. Phase 5 has not been built, so a scan is a
    degraded success: real findings, no explanations. Saying so is better than
    a field that silently means something else later."""
    report = browser_work["first"]

    assert report["explanations_available"] is False
    assert report["explanations_unavailable_reason"] == "api_unavailable"
    assert all(issue["explanation"] is None for issue in report["issues"])
    assert all(issue["fix"] is None for issue in report["issues"])


def test_a_real_scan_finds_the_planted_faults(browser_work):
    """The whole pipeline, end to end: navigate, inject axe, run it,
    translate the result."""
    found = {issue["rule_id"] for issue in browser_work["first"]["issues"]}

    assert {"image-alt", "label", "button-name", "color-contrast"} <= found


def test_the_same_browser_serves_every_scan(browser_work):
    """Task 4.6, stated as the thing that is actually true.

    Not "the second scan is faster than the first" -- measuring that showed
    the two are about equal, because both run on a browser that is already
    warm. The property worth asserting is that the browser is never
    relaunched, and that is exact rather than a timing margin.
    """
    assert browser_work["browser_before"] == browser_work["browser_after"]
    assert browser_work["first"]["url"] == browser_work["second"]["url"]


def test_reuse_saves_the_cost_of_launching_a_browser(browser_work):
    """Task 4.6's "Done when", measured against the right baseline.

    A warm scan is compared with starting a browser *and* scanning, which is
    what every request would cost without reuse. The margin is large -- most
    of a second of Chromium startup against a fraction of a second of scanning
    -- so this does not turn into a performance assertion that fails on a busy
    laptop. `scripts/scan_loop_check.py` prints the real numbers.
    """
    warm = browser_work["second_elapsed"]
    cold = browser_work["cold_elapsed"]

    assert warm < cold, f"warm scan {warm:.2f}s, cold start plus scan {cold:.2f}s"


def test_both_scans_found_the_same_things(browser_work):
    """Reuse must not mean leakage. Each scan gets a fresh context -- its own
    cookies, storage and cache -- so the second scan of an unchanged page must
    produce exactly what the first did."""
    first = [issue["id"] for issue in browser_work["first"]["issues"]]
    second = [issue["id"] for issue in browser_work["second"]["issues"]]

    assert first == second


def test_a_page_that_is_not_there_is_unreachable(browser_work):
    assert browser_work["missing_page_error"].code == "unreachable"
    assert browser_work["missing_page_error"].status_code == 502


def test_the_browser_starts_and_stops_with_the_app(browser_work):
    """A browser left running is a Chromium process left behind, and on a
    memory-limited host that is the difference between a restart working and
    a restart being killed."""
    assert browser_work["running_before_start"] is False
    assert browser_work["running_after_start"] is True
    assert browser_work["running_after_stop"] is False


def test_scanning_before_start_is_a_programming_error():
    """Not an ApiError: no URL the user could type causes this, so turning it
    into a polite 400 would hide a bug."""
    with pytest.raises(ScannerNotStarted):
        asyncio.run(Scanner().scan("https://example.com", timeout_ms=1000))


# --- Task 4.4: every failure gets a contract code ---------------------------


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class FakePage:
    """Just enough page to drive _goto. Whatever `outcome` is gets raised if
    it is an exception, and returned otherwise."""

    def __init__(self, outcome) -> None:
        self.outcome = outcome

    async def goto(self, url, wait_until=None, timeout=None):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def goto(outcome):
    return asyncio.run(_goto(FakePage(outcome), "https://example.com", 30_000))


def test_a_page_that_never_loads_is_a_timeout():
    with pytest.raises(ApiError) as caught:
        goto(PlaywrightTimeoutError("Timeout 30000ms exceeded"))

    assert caught.value.code == "scan_timeout"
    assert caught.value.status_code == 504
    assert "30 seconds" in (caught.value.detail or "")


NETWORK_FAILURES = [
    pytest.param("net::ERR_NAME_NOT_RESOLVED", "unreachable", id="no-such-domain"),
    pytest.param("net::ERR_CONNECTION_REFUSED", "unreachable", id="refused"),
    pytest.param("net::ERR_CERT_AUTHORITY_INVALID", "unreachable", id="bad-certificate"),
    pytest.param("net::ERR_TOO_MANY_REDIRECTS", "unreachable", id="redirect-loop"),
    pytest.param("net::ERR_CONNECTION_TIMED_OUT", "scan_timeout", id="connect-timeout"),
    pytest.param("net::ERR_TIMED_OUT", "scan_timeout", id="timed-out"),
]


@pytest.mark.parametrize("message,expected_code", NETWORK_FAILURES)
def test_chromiums_network_errors_become_contract_codes(message, expected_code):
    """A connection that times out is a timeout, not an unreachable host: one
    is worth retrying and the other is not, and the person reading the message
    is the one who has to decide."""
    with pytest.raises(ApiError) as caught:
        goto(PlaywrightError(message))

    assert caught.value.code == expected_code


def test_no_exception_message_reaches_the_user():
    """Chromium's error text can carry local paths. The code is enough."""
    with pytest.raises(ApiError) as caught:
        goto(PlaywrightError("net::ERR_FILE_NOT_FOUND at C:\\Users\\someone\\secret"))

    assert "C:\\Users" not in (caught.value.detail or "")
    assert "net::" not in (caught.value.detail or "")


def test_a_successful_response_passes_straight_through():
    assert goto(FakeResponse(200)).status == 200


@pytest.mark.parametrize("status", [400, 403, 404, 410, 500, 502, 503])
def test_an_error_page_from_the_target_is_unreachable(status):
    """Arguable, and settled by the contract: someone who typed a URL
    expecting a page has not got one, so reporting on the accessibility of the
    error page would answer a question they did not ask."""
    with pytest.raises(ApiError) as caught:
        _reject_unsuccessful_response(FakeResponse(status))

    assert caught.value.code == "unreachable"
    assert str(status) in (caught.value.detail or "")


@pytest.mark.parametrize("status", [200, 201, 204, 301, 302, 399])
def test_a_working_page_is_not_rejected(status):
    assert _reject_unsuccessful_response(FakeResponse(status)) is None


def test_no_response_at_all_is_unreachable():
    with pytest.raises(ApiError) as caught:
        _reject_unsuccessful_response(None)

    assert caught.value.code == "unreachable"


# --- The DNS-rebinding mitigation: every request, not just the first --------


class FakeRoute:
    def __init__(self) -> None:
        self.action: str | None = None

    async def continue_(self) -> None:
        self.action = "continue"

    async def abort(self) -> None:
        self.action = "abort"


class FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class RecordingPage:
    """Captures the handler that _block_requests_to_private_addresses installs,
    so it can be called directly with requests of our choosing."""

    def __init__(self) -> None:
        self.handler = None

    async def route(self, pattern, handler) -> None:
        self.handler = handler


def route_decision(url: str) -> str:
    """What the filter does with a request for this URL."""

    async def main() -> str:
        page = RecordingPage()
        await _block_requests_to_private_addresses(page)
        route = FakeRoute()
        await page.handler(route, FakeRequest(url))
        return route.action

    return asyncio.run(main())


BLOCKED_REQUESTS = [
    pytest.param("http://169.254.169.254/latest/meta-data/", id="metadata-service"),
    pytest.param("http://127.0.0.1:8000/admin", id="loopback"),
    pytest.param("http://10.0.0.5/internal.png", id="private-network"),
    pytest.param("https://192.168.1.1/router", id="home-router"),
]


@pytest.mark.parametrize("url", BLOCKED_REQUESTS)
def test_the_page_cannot_fetch_private_addresses(url):
    """The mitigation promised in the DNS-rebinding entry in DECISIONS.md.

    check_url sees only the address someone typed. A page can embed
    `<img src="http://169.254.169.254/latest/meta-data/">`, and every redirect
    and sub-resource does its own lookup. This handler sees all of them.
    """
    assert route_decision(url) == "abort"


ALLOWED_REQUESTS = [
    pytest.param("https://example.com/style.css", id="ordinary-request"),
    pytest.param("data:image/svg+xml,%3Csvg%3E%3C/svg%3E", id="data-uri"),
    pytest.param("blob:https://example.com/abc-123", id="blob"),
    pytest.param("file:///C:/tmp/fixture.html", id="local-file-fixture"),
]


@pytest.mark.parametrize("url", ALLOWED_REQUESTS)
def test_ordinary_requests_are_left_alone(url):
    """Non-http schemes go nowhere near the network, and the test fixture is a
    local file. Chromium already refuses `file:` sub-resources from an http
    page, so letting them past here is not the hole it looks like."""
    assert route_decision(url) == "continue"


def test_a_blocked_request_does_not_fail_the_whole_scan():
    """Aborted, not raised. One blocked image should not lose the report: the
    page renders without it and axe reports on what actually loaded."""
    assert route_decision("http://127.0.0.1/tracker.gif") == "abort"


# --- Task 5.6: the endpoint composes a scan and an explanation --------------
#
# These tests stub the scanner rather than driving a browser, because the thing
# under test is the *wiring*: that explaining happens after scanning, that a
# failed explanation cannot fail the request, and that the response FastAPI
# serialises still matches the contract field for field.
#
# Scanning a real page through this endpoint is not possible without the
# internet, and deliberately so: the fixture lives on disk, and `check_url`
# refuses both `file://` and loopback addresses. That refusal is Phase 3
# working as intended, so the live end-to-end check belongs in a manual run
# against a public URL, not in a test suite that has to pass offline.


def test_a_scan_returns_findings_when_explanations_are_unavailable(stub_scanner):
    """Task 5.6's "done when", at the level of the HTTP response: when
    explanations cannot be had, the findings still come back and the body is
    still contract-shaped.

    There is no lifespan here -- see the module docstring -- so the explainer
    holds no client, which is the same situation as a blanked-out API key from
    the endpoint's point of view. It is also a guarantee worth having in a test
    suite: with no client there is nothing that *could* reach the network, so
    these tests cannot quietly start spending money.

    (`tests/test_explainer.py` covers the placeholder-key path specifically.
    The key in `conftest.py` is fake but well-formed, so `enabled` is True
    here; what stops the call is the missing client.)"""
    assert main.explainer.is_running is False

    response = client.post("/scan", json={"url": "https://example.com"}, headers=CODE)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] == 2
    assert len(body["issues"]) == 2
    assert body["explanations_available"] is False
    assert body["explanations_unavailable_reason"] == "api_unavailable"
    assert all(issue["explanation"] is None for issue in body["issues"])
    assert all(issue["fix"] is None for issue in body["issues"])


def test_the_degraded_body_has_exactly_the_contract_keys(stub_scanner):
    response = client.post("/scan", json={"url": "https://example.com"}, headers=CODE)
    body = response.json()

    assert set(body) == {
        "url", "page_title", "scanned_at", "scan_duration_ms",
        "explanations_available", "explanations_unavailable_reason",
        "summary", "issues",
    }
    assert set(body["issues"][0]) == {
        "id", "rule_id", "severity", "wcag", "reference_url",
        "selector", "html", "explanation", "fix",
    }


def test_an_explained_body_omits_the_unavailable_reason_entirely(
    stub_scanner, monkeypatch
):
    """The contract says that key is present *only* when explanations are
    unavailable. A `null` in its place would be a different shape, and the
    frontend is entitled to read the key's presence as the signal -- so this
    checks the JSON that actually goes over the wire, after FastAPI's
    response_model has had its say."""

    async def fake_explain(report: Report) -> Report:
        for issue in report["issues"]:
            issue["explanation"] = {"what": "No alt attribute.", "who": "A screen reader user hears nothing."}
            issue["fix"] = {
                "language": "html",
                "snippet": '<img src="/picture-0.png" alt="A picture">',
                "assumptions": ["Assumed the subject of the picture."],
            }
        report["explanations_available"] = True
        report.pop("explanations_unavailable_reason", None)
        return report

    monkeypatch.setattr(main.explainer, "explain", fake_explain)

    body = client.post("/scan", json={"url": "https://example.com"}, headers=CODE).json()

    assert body["explanations_available"] is True
    assert "explanations_unavailable_reason" not in body
    assert body["issues"][0]["explanation"]["what"] == "No alt attribute."
    assert body["issues"][0]["fix"]["assumptions"] == [
        "Assumed the subject of the picture."
    ]


def test_a_blocked_url_never_reaches_the_explainer(monkeypatch):
    """The order the whole of Phase 3 exists to guarantee, now with a third
    step behind it: nothing is fetched and nothing is explained until the
    address has been approved."""
    called: list[str] = []

    async def record(report: Report) -> Report:
        called.append("explained")
        return report

    monkeypatch.setattr(main.explainer, "explain", record)

    response = client.post("/scan", json={"url": "http://localhost"}, headers=CODE)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "blocked_address"
    assert called == []


def test_an_explainer_that_raises_would_not_be_hidden(stub_scanner, monkeypatch):
    """The explainer promises never to raise, and `app.main` leans on that
    promise rather than wrapping the call in a try block of its own.

    A second safety net there would be dead code in every passing case and
    would quietly swallow a real bug. So the promise is tested instead: if the
    explainer ever breaks it, that surfaces as a loud failure rather than as a
    silently half-filled report."""

    async def exploding_explain(report: Report) -> Report:
        raise RuntimeError("a bug in the explainer")

    monkeypatch.setattr(main.explainer, "explain", exploding_explain)

    # TestClient re-raises what the server raised, which is what makes this
    # visible at all. In production the same exception reaches app.errors and
    # becomes the contract's internal_error, tested in tests/test_errors.py.
    with pytest.raises(RuntimeError, match="a bug in the explainer"):
        client.post("/scan", json={"url": "https://example.com"}, headers=CODE)
