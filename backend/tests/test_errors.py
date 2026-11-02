"""Task 2.5 — one error shape for every failure.

The frontend branches on `error.code` and never on `error.message`. That only
works if *every* failure arrives in this shape, including the ones a web
framework answers by itself. These tests are mostly about the boring failures,
because those are the ones that escape in the wrong format.
"""

import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import (
    CODE_FOR_STATUS,
    DEFAULT_MESSAGE,
    STATUS_FOR_CODE,
    ApiError,
    register_error_handlers,
    register_request_logging,
)
from app.main import app

client = TestClient(app)


def assert_contract_shape(body: dict) -> dict:
    """Every error response, without exception, looks like this."""
    assert set(body) == {"error"}, "top level must be exactly {'error': ...}"
    error = body["error"]
    assert set(error) == {"code", "message", "detail"}
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    assert error["detail"] is None or isinstance(error["detail"], str)
    return error


# --- The failures a framework answers by itself -----------------------------

def test_unknown_route_returns_the_contract_shape():
    """The task's stated "Done when".

    Without a handler this is FastAPI's {"detail": "Not Found"}, which the
    frontend's error parser would not recognise.
    """
    response = client.get("/no-such-route")

    assert response.status_code == 404
    error = assert_contract_shape(response.json())
    assert error["code"] == "not_found"
    assert "detail" not in error["message"].lower()


def test_wrong_method_returns_the_contract_shape():
    response = client.post("/health")

    assert response.status_code == 405
    assert assert_contract_shape(response.json())["code"] == "method_not_allowed"


def test_no_response_uses_fastapis_default_error_key():
    """Guards the whole point: a bare `detail` key at the top level means some
    failure slipped past the handlers."""
    for path, method in [("/no-such-route", "get"), ("/health", "post")]:
        body = getattr(client, method)(path).json()
        assert "detail" not in body, f"{method.upper()} {path} escaped the shape"


# --- ApiError ---------------------------------------------------------------

def test_api_error_derives_its_status_from_its_code():
    assert ApiError("blocked_address").status_code == 400
    assert ApiError("scan_timeout").status_code == 504
    assert ApiError("daily_limit_reached").status_code == 429


def test_api_error_rejects_an_unknown_code():
    """A typo would otherwise reach the frontend and match none of its cases."""
    with pytest.raises(ValueError, match="unknown error code"):
        ApiError("not_a_real_code")  # type: ignore[arg-type]


def test_api_error_has_a_default_message_for_every_code():
    """`message` is shown to the user as-is, so none may be blank."""
    for code in STATUS_FOR_CODE:
        assert DEFAULT_MESSAGE.get(code), f"{code} has no default message"


def test_a_raised_api_error_becomes_the_contract_shape():
    """Exercised on a throwaway app, since the real one has no failing route
    until Phase 3."""
    scratch = FastAPI()
    register_error_handlers(scratch)

    @scratch.get("/boom")
    def boom():
        raise ApiError("blocked_address", detail="Hostname resolved to 127.0.0.1")

    response = TestClient(scratch).get("/boom")

    assert response.status_code == 400
    error = assert_contract_shape(response.json())
    assert error["code"] == "blocked_address"
    assert error["detail"] == "Hostname resolved to 127.0.0.1"


# --- Unexpected failures must not leak ---------------------------------------

def test_an_unexpected_exception_leaks_nothing(caplog):
    """The most important test here.

    An exception message can carry file paths, query fragments or key material,
    and this response goes to a stranger. The cause belongs in the log.
    """
    scratch = FastAPI()
    register_error_handlers(scratch)
    secret = "sk-ant-this-must-never-be-returned"

    @scratch.get("/explode")
    def explode():
        raise RuntimeError(f"connection failed using {secret}")

    with caplog.at_level(logging.ERROR, logger="a11y_lens"):
        response = TestClient(scratch, raise_server_exceptions=False).get("/explode")

    assert response.status_code == 500
    error = assert_contract_shape(response.json())
    assert error["code"] == "internal_error"

    serialised = response.text
    assert secret not in serialised
    assert "RuntimeError" not in serialised
    assert "Traceback" not in serialised

    # Still diagnosable: the response carries a reference that appears in the
    # log beside the real cause.
    reference = re.search(r"Reference ([0-9a-f]{12})", error["detail"] or "")
    assert reference, "no incident reference in detail"
    assert reference.group(1) in caplog.text
    assert secret in caplog.text, "the real cause must reach the log"


# --- Request logging ---------------------------------------------------------

def test_requests_are_logged_without_the_access_code(caplog):
    """`X-Access-Code` travels in a header. Logging request headers wholesale
    is the fastest way to put a secret in a log file, so the middleware logs
    method, path, status and duration and nothing else."""
    scratch = FastAPI()
    register_request_logging(scratch)

    @scratch.get("/thing")
    def thing():
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="a11y_lens"):
        TestClient(scratch).get(
            "/thing?token=should-not-be-logged",
            headers={"X-Access-Code": "super-secret-code"},
        )

    assert "GET /thing -> 200" in caplog.text
    assert "super-secret-code" not in caplog.text
    assert "should-not-be-logged" not in caplog.text


# --- The two tables must agree ----------------------------------------------

def test_status_mappings_are_consistent():
    """CODE_FOR_STATUS maps a status onto a code; STATUS_FOR_CODE must send
    that code back to the same status, or a bare HTTPException would come back
    with a code whose documented status is different."""
    for status, code in CODE_FOR_STATUS.items():
        assert STATUS_FOR_CODE[code] == status, (
            f"{code} maps to {STATUS_FOR_CODE[code]}, not {status}"
        )
