"""Task 2.2 — the test harness, proved on the one endpoint that exists.

These tests assert the contract in docs/api-contract.md, not merely that the
endpoint returns something. The contract says a response is always an object
with both keys, so that is what gets checked: a frontend reading
`response.version` must not get `undefined` because someone trimmed the
response later.
"""

from fastapi.testclient import TestClient

from app.main import API_VERSION, app

# TestClient calls the app directly, with no network and no running server, so
# the suite does not need uvicorn started first.
client = TestClient(app)


def test_health_returns_200():
    assert client.get("/health").status_code == 200


def test_health_reports_ok_and_a_version():
    body = client.get("/health").json()
    assert body == {"status": "ok", "version": API_VERSION}


def test_health_response_is_an_object():
    """Contract rule 7: never a bare string or array at the top level.

    An object can gain fields without breaking any client; an array or a string
    cannot. Worth a test of its own because it is the kind of thing a later
    refactor breaks without noticing.
    """
    assert isinstance(client.get("/health").json(), dict)


def test_health_needs_no_authentication():
    """The contract says /health takes no access code.

    Once Phase 6 adds the access-code gate to /scan, it would be easy to apply
    it globally by accident -- which would stop the deploy host from being able
    to see that the service is alive.
    """
    response = client.get("/health", headers={})
    assert response.status_code == 200
