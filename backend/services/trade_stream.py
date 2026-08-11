"""Live trade events from the simulated account, over gRPC.

Resting exits are the reason this exists. A stop or a take-profit can fill at
any moment, and nobody is waiting for that fill — so it was only noticed when
the watchdog next polled, up to fifteen minutes later. A stream tells us within
a second.

**Events are a trigger, not a data source.** Every event does the same thing:
re-run the settle path that already reads order details from the REST API and
is already verified against a real fill. Parsing the event payload instead
would put the fill price and quantity on a code path that has never been seen
in production — and the last time this app trusted an unverified payload shape,
the combo wrapper meant every fill stayed pending forever.

The 15-minute poll stays exactly as it was. A stream that silently stops is
worse than no stream, so this is a latency improvement layered over a
correctness guarantee, never a replacement for it.

The subscription is blocking, so it runs on its own daemon thread; callbacks
arrive on that thread and must not touch the event loop directly.
"""
import asyncio
import logging
import os
import sys
import threading

from backend.services import quotes, sandbox_broker

log = logging.getLogger("trading-bot.trade_stream")

# The events API has its own host and its own resolver, so the sandbox override
# applied to the REST client (backend/services/quotes.py) does not reach it.
# Pointing production credentials at the sandbox host, or the reverse, simply
# fails to authenticate — but relying on that is not a safety story, which is
# why nothing here can place an order.
_SANDBOX_EVENTS_HOST = "events-api.sandbox.webull.com"

class _MuteThisThread:
    """A stdout proxy that drops writes from the stream thread only.

    The SDK prints its connection parameters — including the app key and the
    request signature — straight to stdout on every connect, for the same
    reason quotes.py has to silence its token logging: credential material has
    no business in routine logs.

    Redirecting stdout wholesale was the obvious fix and the wrong one. sys.stdout
    is global, so for as long as the stream ran, *everything* that printed
    anywhere in the process vanished. Filtering by thread keeps the rest of the
    program's output intact.
    """

    def __init__(self, wrapped, muted_thread_name: str):
        self._wrapped = wrapped
        self._muted = muted_thread_name

    def write(self, text):
        if threading.current_thread().name == self._muted:
            return len(text)
        return self._wrapped.write(text)

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


_STREAM_THREAD_NAME = "webull-trade-events"
_thread: threading.Thread | None = None
_loop: asyncio.AbstractEventLoop | None = None
_client = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def _on_event(client, payload, response) -> None:
    """Something changed on the account. Go and look, using the path that is
    known to read fills correctly."""
    # Logged verbatim: the payload shape has never been observed in this app,
    # and the first real one is worth having in the logs to read later.
    log.info("Trade event: %s", str(payload)[:500])
    try:
        from backend.services import agent

        settled = agent.settle_pending()
    except Exception:
        log.exception("Couldn't settle after a trade event")
        return
    if not settled:
        return
    log.info("Settled %d order(s) from a trade event", len(settled))
    for fill in settled:
        if fill.get("was_stop") and fill.get("status") == "filled":
            _notify_from_thread(fill)


def _notify_from_thread(fill: dict) -> None:
    """Hand a Discord post back to the main loop.

    The callback runs on the gRPC thread. notify() touches the Discord client,
    which belongs to the loop the app started on, so it has to be scheduled
    there rather than awaited here.
    """
    if _loop is None or _loop.is_closed():
        return
    from backend.discord_bot.notify import notify
    from backend.services import agent

    try:
        asyncio.run_coroutine_threadsafe(notify(agent.format_stop_fill(fill)), _loop)
    except Exception:
        log.exception("Couldn't post a fill notification from the stream thread")


def _on_connect(client, payload, response) -> None:
    log.info("Trade event stream connected")


def _run(account_id: str, app_key: str, app_secret: str) -> None:
    from webull.trade.trade_events_client import TradeEventsClient

    global _client
    while True:
        try:
            _client = TradeEventsClient(app_key, app_secret, host=_SANDBOX_EVENTS_HOST)
            _client.on_connect = _on_connect
            _client.on_events_message = _on_event
            _client.on_log = lambda level, text: log.debug("stream: %s", str(text)[:300])
            _client.do_subscribe([account_id])
        except Exception:
            log.exception("Trade event stream dropped")
        # do_subscribe returns when the stream ends, retries exhausted included.
        # Reconnecting is safe because settle_pending is idempotent — it only
        # acts on orders still marked pending.
        log.warning("Trade event stream ended; reconnecting in 60s")
        if _stop.wait(60):
            return


_stop = threading.Event()


def start() -> bool:
    """Begin streaming, if there is a simulated account to stream. Returns
    whether it started.

    Never fatal: the app runs fine without it, just with the old fifteen-minute
    latency on a resting exit.
    """
    global _thread, _loop
    if is_running():
        return True
    if not quotes.is_sandbox():
        log.info("Not in sandbox — trade event stream not started")
        return False
    app_key = os.environ.get("WEBULL_APP_KEY")
    app_secret = os.environ.get("WEBULL_APP_SECRET")
    if not app_key or not app_secret:
        return False
    try:
        account_id = sandbox_broker.get_paper_account_id()
    except Exception:
        log.exception("Couldn't resolve the simulated account for the event stream")
        return False
    if not account_id:
        return False

    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
    _stop.clear()
    if not isinstance(sys.stdout, _MuteThisThread):
        sys.stdout = _MuteThisThread(sys.stdout, _STREAM_THREAD_NAME)
    _thread = threading.Thread(
        target=_run, args=(account_id, app_key, app_secret), name=_STREAM_THREAD_NAME, daemon=True
    )
    _thread.start()
    log.info("Trade event stream starting for %s", account_id)
    return True


def stop() -> None:
    _stop.set()
