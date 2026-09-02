"""The published copy refuses every write.

The experiment is meant to be read by anyone. The small write surface — the
settings that choose the model and the budget, and the endpoint that places exit
orders — is not.

These test the middleware rather than the routes, because that is where the
guarantee lives: a per-route check protects only the routes somebody remembered
to annotate, and the route added next year is the case that matters.
"""
import pytest
from fastapi.testclient import TestClient

from backend.services import publish


@pytest.fixture
def client(monkeypatch):
    def build(public: bool):
        if public:
            monkeypatch.setenv("PUBLIC_MODE", "1")
        else:
            monkeypatch.delenv("PUBLIC_MODE", raising=False)
        from backend.app import app

        return TestClient(app)

    return build


# --- reading the flag ----------------------------------------------------------


def test_a_deployment_is_private_by_default(monkeypatch):
    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    assert publish.is_public() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_public_is_opt_in(monkeypatch, value):
    monkeypatch.setenv("PUBLIC_MODE", value)
    assert publish.is_public() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off", "maybe"])
def test_anything_else_stays_private(monkeypatch, value):
    """A flag that opens a write surface must fail towards keeping it shut, so
    an unrecognised value means private rather than public."""
    monkeypatch.setenv("PUBLIC_MODE", value)
    assert publish.is_public() is False


# --- what the middleware does --------------------------------------------------


def test_a_write_is_refused_when_public(client):
    response = client(True).patch("/api/settings", json={"horizon": "position"})
    assert response.status_code == 403
    assert "read-only" in response.json()["detail"]


def test_the_exits_endpoint_is_refused_too(client):
    """The one write that decides nothing is still a write: it places live
    orders at the broker."""
    assert client(True).post("/api/agent/exits/AAPL").status_code == 403


def test_a_route_nobody_annotated_is_refused(client):
    """The guarantee is the method, not a list of paths. A POST to a path that
    does not exist must be refused before routing, or the protection depends on
    somebody remembering to annotate each new route."""
    assert client(True).post("/api/some/route/added/later").status_code == 403


def test_reading_still_works_when_public(client):
    assert client(True).get("/api/settings").status_code == 200


def test_writes_are_allowed_when_private(client):
    """Not 403. It may still fail validation or hit the sandbox guard — what
    matters is that the public middleware is not what stopped it."""
    assert client(False).patch("/api/settings", json={}).status_code != 403


def test_the_settings_payload_says_which_copy_this_is(client):
    assert client(True).get("/api/settings").json()["public"] is True
    assert client(False).get("/api/settings").json()["public"] is False


# --- the half that is not about HTTP at all ------------------------------------


def test_the_published_copy_runs_no_jobs(monkeypatch):
    """Two containers over one database must not both run the agent.

    This is the half of PUBLIC_MODE that matters most. A second copy running
    the scheduler would sweep twice — paying twice for the same research — and
    decide twice at 13:35, placing two sets of orders against one ledger. None
    of that arrives as an HTTP request, so refusing writes would not stop any
    of it.
    """
    import asyncio

    monkeypatch.setenv("PUBLIC_MODE", "1")
    started = []
    monkeypatch.setattr("backend.app.register_jobs", lambda: started.append("jobs"))
    monkeypatch.setattr("backend.app.scheduler.start", lambda: started.append("scheduler"))
    monkeypatch.setattr("backend.app.trade_stream.start", lambda: started.append("stream"))

    async def fake_discord():
        started.append("discord")

    monkeypatch.setattr("backend.app.start_discord", fake_discord)

    from backend.app import lifespan

    async def run():
        async with lifespan(None):
            pass

    asyncio.run(run())
    assert started == []


def test_the_private_copy_starts_everything(monkeypatch):
    import asyncio

    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    started = []
    monkeypatch.setattr("backend.app.register_jobs", lambda: started.append("jobs"))
    monkeypatch.setattr("backend.app.scheduler.start", lambda: started.append("scheduler"))
    monkeypatch.setattr("backend.app.scheduler.shutdown", lambda: None)
    monkeypatch.setattr("backend.app.trade_stream.start", lambda: started.append("stream"))
    monkeypatch.setattr("backend.app.trade_stream.stop", lambda: None)

    async def fake_start():
        started.append("discord")

    async def fake_stop():
        pass

    monkeypatch.setattr("backend.app.start_discord", fake_start)
    monkeypatch.setattr("backend.app.stop_discord", fake_stop)

    from backend.app import lifespan

    async def run():
        async with lifespan(None):
            pass

    asyncio.run(run())
    assert set(started) == {"jobs", "scheduler", "stream", "discord"}
