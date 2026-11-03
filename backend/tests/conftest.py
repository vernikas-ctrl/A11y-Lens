"""Shared test setup.

`app.main` validates configuration at import, so the environment has to be
populated before any test module imports it. conftest.py is imported before
test modules, which makes this the right place.

These values are fake and exist only so the app can start. The real ones live
in backend/.env, which is git-ignored and deliberately not read here -- a test
suite that depends on a developer's personal .env passes or fails for reasons
that have nothing to do with the code.
"""

import os

TEST_ENVIRONMENT = {
    "ANTHROPIC_API_KEY": "sk-ant-not-a-real-key-for-tests-only",
    "ACCESS_CODE": "test-access-code-not-secret",
    "ALLOWED_ORIGINS": "http://localhost:5173",
    "SCAN_TIMEOUT_MS": "30000",
    "DAILY_SCAN_LIMIT": "50",
    "ENVIRONMENT": "development",
    # Deliberately permissive. The suite fires dozens of requests from one
    # address, and the real default of 5 a minute would rate-limit the tests
    # themselves -- which would look like a bug in whatever test ran sixth.
    # The limiter is tested as a unit, and once through the endpoint with a
    # strict limiter injected on purpose. See tests/test_limits.py.
    "RATE_LIMIT_PER_MINUTE": "600",
    "TRUSTED_PROXY_HOPS": "0",
}

# setdefault, not assignment: CI may want to override one of these, and this
# should not fight it.
for _key, _value in TEST_ENVIRONMENT.items():
    os.environ.setdefault(_key, _value)


# --- Shared test doubles ----------------------------------------------------
#
# Imported here rather than kept in one test module, because both
# test_scan_endpoint.py and test_limits.py drive /scan and neither of them
# wants a real browser. Defined after the environment above, since importing
# app.* validates configuration.

import pytest  # noqa: E402

from app import main  # noqa: E402
from app.scanner import Report  # noqa: E402


def canned_report(issue_count: int = 2) -> Report:
    """What `Scanner.scan` hands back: real findings, nothing explained yet."""
    return {
        "url": "https://example.com/",
        "page_title": "Example Domain",
        "scanned_at": "2026-11-03T12:00:00Z",
        "scan_duration_ms": 900,
        "explanations_available": False,
        "explanations_unavailable_reason": "api_unavailable",
        "summary": {
            "critical": 0,
            "serious": issue_count,
            "moderate": 0,
            "minor": 0,
            "total": issue_count,
        },
        "issues": [
            {
                "id": f"image-alt-{index}",
                "rule_id": "image-alt",
                "severity": "serious",
                "wcag": ["1.1.1"],
                "reference_url": "https://dequeuniversity.com/rules/axe/4.14/image-alt",
                "selector": f"main > img:nth-child({index + 1})",
                "html": f'<img src="/picture-{index}.png">',
                "explanation": None,
                "fix": None,
            }
            for index in range(issue_count)
        ],
    }


@pytest.fixture
def stub_scanner(monkeypatch):
    """Replace the browser with a canned report, leaving everything else real.

    A scan of a real page cannot go through /scan in a test: the fixture lives
    on disk and `check_url` correctly refuses both file:// and loopback. So
    anything testing the endpoint's own behaviour stubs the scan.
    """

    async def fake_scan(url: str, timeout_ms: int) -> Report:
        del url, timeout_ms
        return canned_report()

    monkeypatch.setattr(main.scanner, "scan", fake_scan)
