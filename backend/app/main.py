"""The FastAPI application.

Task 2.1 builds only the health check. Everything else arrives in later phases:
configuration in 2.3, CORS in 2.4, the shared error shape in 2.5, URL safety in
Phase 3, and the actual scan endpoint in Phase 4.

The health check is first because every later task needs a way to ask "is the
server up?" that does not depend on anything else working.
"""

from fastapi import FastAPI

# Bumped by hand when the response shape changes, so a deployed frontend can
# tell which backend it is talking to. Not the git tag and not read from the
# package metadata -- this is the API's version, not the project's.
API_VERSION = "0.1.0"

app = FastAPI(
    title="A11y-Lens API",
    version=API_VERSION,
    description="Scans a web page for accessibility issues and explains them.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check.

    Deliberately does no work: it must answer even when the browser, the Claude
    API or anything else is broken, because its job is to distinguish "the
    server is down" from "the server is up and something else is wrong".

    No authentication, by the contract in docs/api-contract.md -- the deploy
    host has to be able to call it, and it reveals nothing.
    """
    return {"status": "ok", "version": API_VERSION}
