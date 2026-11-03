"""The access code. Task 6.2.

The app is link-only, so this is the front door rather than a step in the
middle. Four things are worth holding the code to, and they are the four groups
below: it refuses without a valid code, it refuses in the contract's shape, the
comparison cannot be timed, and the secret does not end up written down
anywhere.
"""

import secrets
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.auth import AccessCode
from app.config import get_settings
from app.errors import ApiError

client = TestClient(main.app)

REAL_CODE = get_settings().access_code.get_secret_value()
CODE = {"X-Access-Code": REAL_CODE}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --- Does it let the right people through -----------------------------------


def test_the_right_code_is_accepted():
    response = client.post("/verify", headers=CODE)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize(
    "offered",
    [
        pytest.param("", id="empty"),
        pytest.param("wrong", id="wrong-and-short"),
        pytest.param("x" * len(REAL_CODE), id="wrong-but-right-length"),
        pytest.param(REAL_CODE[:-1], id="almost-right"),
        pytest.param(REAL_CODE + "x", id="right-plus-one"),
        pytest.param(REAL_CODE.upper(), id="wrong-case"),
        pytest.param(f" {REAL_CODE} ", id="padded-with-spaces"),
    ],
)
def test_a_wrong_code_is_refused(offered):
    """Including the near-misses. No trimming and no case-folding: a code that
    almost matches is a code that does not match, and being generous about it
    would make the near-miss attacks below cheaper."""
    response = client.post("/verify", headers={"X-Access-Code": offered})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_no_code_at_all_is_refused_and_says_what_to_send():
    response = client.post("/verify")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert "X-Access-Code" in body["error"]["detail"]


def test_scanning_without_the_code_is_refused_before_anything_happens():
    """Task 6.2's "done when". The 401 is also positive evidence of ordering:
    no lifespan runs in this file, so the scanner holds no browser -- if an
    unauthorised request ever reached it, the result would be a 500 rather
    than a clean 401."""
    response = client.post("/scan", json={"url": "https://example.com"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_health_needs_no_code():
    """By the contract: the deploy host has to be able to call it, and it
    reveals nothing."""
    assert client.get("/health").status_code == 200
    assert client.get("/health").json()["status"] == "ok"


# --- Is it the contract's shape ---------------------------------------------


def test_the_refusal_has_exactly_the_contract_error_shape():
    body = client.post("/verify").json()

    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "detail"}
    assert body["error"]["code"] == "unauthorized"


def test_the_message_does_not_promise_a_public_demo_page():
    """It used to, and DECISIONS.md changed on 2026-11-03: the app is
    link-only, so there is no page to see without a code. A message that
    invites somebody to go and look at something that does not exist is worse
    than a terse one."""
    message = client.post("/verify").json()["error"]["message"].lower()

    assert "without one" not in message
    assert "demo" not in message


# --- Can the comparison be timed --------------------------------------------


def test_the_comparison_is_timing_safe(monkeypatch):
    """`==` on strings stops at the first differing byte, so how fast a wrong
    code is rejected leaks how much of it was right -- recoverable one
    character at a time, given enough attempts.

    Timing cannot be asserted reliably on a shared machine, so this checks the
    mechanism instead: the constant-time comparison is actually the thing being
    called.
    """
    calls: list[tuple[bytes, bytes]] = []
    real = secrets.compare_digest

    def recording(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.secrets, "compare_digest", recording)

    client.post("/verify", headers={"X-Access-Code": "wrong"})

    assert calls, "a wrong code was compared without secrets.compare_digest"


def test_a_missing_header_is_not_compared_at_all(monkeypatch):
    """Nothing was offered, so there is nothing to compare and no timing to
    equalise. Calling compare_digest against an empty string here would be
    theatre."""
    calls = []
    monkeypatch.setattr(
        auth.secrets, "compare_digest", lambda a, b: calls.append((a, b)) or False
    )

    client.post("/verify")

    assert calls == []


def test_an_empty_expected_code_is_a_programming_error():
    """An empty expected code would make every request valid, which looks
    exactly like working. config.py already requires twelve characters; this
    is the second lock on the same door."""
    with pytest.raises(ValueError):
        AccessCode("")


def test_a_non_ascii_code_is_a_refusal_and_not_a_crash():
    """`secrets.compare_digest` raises on non-ASCII `str`, which is why both
    sides are encoded to bytes before comparing.

    Sent pre-encoded, because an HTTP header cannot carry non-ASCII text at
    all -- the client refuses to encode it, which is a useful thing to know:
    a code with a smart quote in it can never even reach the server. What can
    arrive is bytes outside ASCII, and that has to be a 401 rather than a 500.
    """
    response = client.post(
        "/verify", headers={"X-Access-Code": "paßwort".encode("latin-1")}
    )

    assert response.status_code == 401


# --- Is the secret written down anywhere ------------------------------------


def test_the_real_access_code_is_not_in_the_repository():
    """The other half of task 6.2's "done when": the code appears nowhere in
    the repo.

    Reads the real code out of backend/.env -- which is git-ignored -- and
    searches the tracked files for it. Skipped when there is no .env, so a
    fresh clone and CI do not fail on a file they were never meant to have.
    """
    env_file = REPO_ROOT / "backend" / ".env"
    if not env_file.exists():
        pytest.skip("no backend/.env on this machine")

    secret = None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("ACCESS_CODE="):
            secret = line.split("=", 1)[1].strip()
    if not secret or secret == "change-me-to-something-long-and-random":
        pytest.skip("backend/.env has no real access code set")

    found = subprocess.run(
        ["git", "grep", "-l", "--fixed-strings", secret],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # git grep exits 1 when it finds nothing, which is the result we want.
    assert found.returncode == 1, (
        f"the access code appears in tracked files: {found.stdout.strip()}"
    )


def test_a_refused_code_is_not_logged(caplog):
    """A mistyped code in a log file is still somebody's secret, and a
    near-miss would be a hint to whoever reads the logs."""
    offered = "nearly-the-right-code"

    with caplog.at_level("INFO", logger="a11y_lens"):
        client.post("/verify", headers={"X-Access-Code": offered})

    assert caplog.records, "a refusal should leave some trace"
    assert offered not in caplog.text
    assert REAL_CODE not in caplog.text


def test_the_access_code_is_not_in_the_openapi_schema():
    """FastAPI documents headers it knows about. The *name* appearing is fine
    and useful; the value appearing anywhere would not be."""
    schema = client.get("/openapi.json").json()

    assert REAL_CODE not in str(schema)
    assert "X-Access-Code" in str(schema)


def test_raising_unauthorized_directly_still_carries_the_right_status():
    """The code-to-status mapping lives in one place, so a raise site cannot
    pair them wrongly."""
    error = ApiError("unauthorized")

    assert error.status_code == 401
