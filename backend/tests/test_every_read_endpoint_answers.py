"""Every GET on the API returns 200 against an empty database.

**This exists because `/api/digest` returned a 500 in production and no test
caught it.** The response model kept two fields the service had stopped
building, so `DigestOut` failed validation on every request. Each half was
tested on its own; nothing tested that the two still fitted together.

An empty database is the right fixture for it. It is what a fresh deployment
has, so a shape error shows up here before anyone sees it — and a serialization
bug does not need data to appear.

This is a smoke test, not a behaviour test. It asserts only that the endpoint
answers. What each one *says* is covered by its own module.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app import app

# Every GET the frontend calls. A route added without a line here is a route
# nothing checks, so add one when you add a route.
READ_ENDPOINTS = [
    "/api/settings",
    "/api/agent",
    "/api/agent/trades",
    "/api/agent/performance",
    "/api/agent/history",
    "/api/agent/curve",
    "/api/agent/unprotected",
    "/api/agent/events",
    "/api/agent/journey/entries",
    "/api/agent/journey",
    "/api/watchlist",
    "/api/tickers",
    "/api/signals",
    "/api/scorecard",
    "/api/digest",
    "/api/regime",
    "/api/alerts",
    "/api/jobs",
    "/api/jobs/tasks",
]


@pytest.fixture
def client(monkeypatch):
    """A client whose price lookups never leave the process.

    The digest prices what the agent holds, and the conftest guard rightly
    refuses to let a test reach the live broker. Stubbing the lookup keeps this
    a test of response shape, which is what it is for.
    """
    monkeypatch.setattr("backend.services.digest.get_current_price", lambda t: 100.0)
    monkeypatch.setattr("backend.services.positions.get_current_price", lambda t: 100.0)
    return TestClient(app)


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_endpoint_answers(client, path):
    response = client.get(path)
    assert response.status_code == 200, (
        f"GET {path} returned {response.status_code}. "
        f"{response.text[:300]}"
    )


def test_the_list_covers_every_get_route():
    """A route that is not in the list above is a route nothing smoke-tests.

    Catching the omission here is the point: the test above cannot fail for a
    route nobody remembered to add to it.
    """
    routed = {
        route.path
        for route in app.routes
        if "GET" in getattr(route, "methods", set())
        and route.path.startswith("/api/")
        and "{" not in route.path  # path params need a real id; tested elsewhere
        and not route.path.startswith("/api/docs")
        and not route.path.startswith("/api/redoc")
        and route.path != "/api/openapi.json"
    }
    missing = routed - set(READ_ENDPOINTS)
    assert not missing, f"These GET routes are not smoke-tested: {sorted(missing)}"
