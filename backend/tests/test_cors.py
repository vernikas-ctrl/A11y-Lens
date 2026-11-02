"""Task 2.4 — CORS.

CORS failures are invisible server-side: the request either never leaves the
browser, or the response arrives and the browser refuses to let the page read
it. Either way the server logs look perfectly healthy and the frontend shows a
network error with no detail. So these behaviours get tests rather than being
checked once by hand and assumed.

The browser check the task actually asks for -- a real `fetch()` from
localhost:5173 -- was done separately; this is the regression net.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ALLOWED = "http://localhost:5173"
FOREIGN = "https://someone-elses-site.example"


def test_preflight_from_the_allowed_origin_is_accepted():
    """The OPTIONS request a browser sends before a POST with custom headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-access-code",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_the_access_code_header_is_permitted():
    """The contract sends the shared code in X-Access-Code.

    If it is not in allow_headers the browser blocks the request before it is
    sent, and the frontend cannot tell that apart from the server being down.
    """
    response = client.options(
        "/health",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-access-code,content-type",
        },
    )

    permitted = response.headers["access-control-allow-headers"].lower()
    assert "x-access-code" in permitted
    assert "content-type" in permitted


def test_a_normal_request_from_the_allowed_origin_is_readable():
    response = client.get("/health", headers={"Origin": ALLOWED})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_an_unknown_origin_is_not_granted_access():
    """The response may still be produced -- CORS is enforced in the browser,
    not the server -- but it must not carry the header that lets a foreign page
    read it."""
    response = client.get("/health", headers={"Origin": FOREIGN})

    assert response.headers.get("access-control-allow-origin") != FOREIGN
    assert response.headers.get("access-control-allow-origin") != "*"


def test_credentials_are_not_allowed():
    """allow_credentials with a permissive origin list is the classic CORS
    hole. Access here is a header the frontend sets, so credentials are never
    needed and stay off."""
    response = client.get("/health", headers={"Origin": ALLOWED})

    assert "access-control-allow-credentials" not in response.headers


def test_origins_come_from_configuration_not_from_code():
    """Task 10.4 narrows this to the real Vercel domain at deploy time, so the
    list must not be hard-coded. Guards against someone 'simplifying' it to a
    literal."""
    import inspect

    import app.main as main_module

    source = inspect.getsource(main_module)
    assert "allow_origins=settings.allowed_origins" in source
