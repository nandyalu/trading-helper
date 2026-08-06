"""Real-time quote source. When WEBULL_APP_KEY/WEBULL_APP_SECRET are set the
Webull OpenAPI snapshot endpoint is used (point it at the sandbox with
WEBULL_SANDBOX=1); otherwise — or on any per-call failure — callers fall back
to yfinance's delayed quote in bot/positions.py. Historical bars everywhere
else stay on yfinance; Webull only upgrades the "price right now" path.

The client is built lazily on first use so the bot runs unchanged with no
keys configured. US_STOCK is tried first and US_ETF second (SPY etc.), with
the working category cached per ticker.
"""
import logging
import os

log = logging.getLogger("trading-bot.quotes")

_SANDBOX_ENDPOINT = "api.sandbox.webull.com"

_api_client = None
_api_client_done = False
_market_data = None
_init_done = False
_category_cache: dict[str, str] = {}

_PRICE_KEYS = ("price", "last_price", "last", "close", "pre_close")
_LIST_KEYS = ("snapshots", "data", "result", "list")


def get_api_client():
    """Shared, token-initialized Webull ApiClient (also used by bot/broker.py);
    None when keys aren't configured or initialization failed."""
    global _api_client, _api_client_done
    if _api_client_done:
        return _api_client
    _api_client_done = True
    app_key = os.environ.get("WEBULL_APP_KEY")
    app_secret = os.environ.get("WEBULL_APP_SECRET")
    if not app_key or not app_secret:
        log.info("Webull keys not configured — real-time quotes fall back to yfinance")
        return None
    try:
        from webull.core.client import ApiClient
        from webull.core.http.initializer.client_initializer import ClientInitializer

        # The SDK's token manager logs access-token values at INFO — keep
        # credential material out of routine logs.
        logging.getLogger("webull").setLevel(logging.WARNING)

        api_client = ApiClient(app_key, app_secret, "us")
        if os.environ.get("WEBULL_SANDBOX", "").lower() in ("1", "true", "yes"):
            api_client.add_endpoint("us", _SANDBOX_ENDPOINT)
            log.info("Webull client enabled (sandbox endpoint)")
        else:
            log.info("Webull client enabled (production endpoint)")
        # Exchanges app key/secret for the x-access-token production requires
        # (asks the endpoint first — sandbox reports tokens disabled and skips).
        # The SDK's DataClient/TradeClient would do this too, but they also
        # force-install a log file in cwd, so initialize directly.
        ClientInitializer.initializer(api_client)
        _api_client = api_client
    except Exception:
        log.exception("Webull client init failed — falling back to yfinance")
        _api_client = None
    return _api_client


def _get_market_data():
    global _market_data, _init_done
    if _init_done:
        return _market_data
    _init_done = True
    api_client = get_api_client()
    if api_client is None:
        return None
    from webull.data.quotes.market_data import MarketData

    _market_data = MarketData(api_client)
    return _market_data


def extract_price(payload) -> float | None:
    """Pull a usable price out of a snapshot response, tolerating the shapes
    Webull uses across endpoints: a bare list of snapshot dicts, a dict
    wrapping that list, or a single dict; prices may arrive as strings."""
    if isinstance(payload, dict):
        for key in _LIST_KEYS:
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict):
        return None
    for key in _PRICE_KEYS:
        value = first.get(key)
        if value in (None, ""):
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


def get_realtime_price(ticker: str) -> float | None:
    """Best-effort Webull snapshot quote; None when unconfigured or failing
    (callers fall back to yfinance)."""
    market_data = _get_market_data()
    if market_data is None:
        return None
    from webull.data.common.category import Category

    categories = [_category_cache.get(ticker)] if ticker in _category_cache else [
        Category.US_STOCK.name,
        Category.US_ETF.name,
    ]
    for category in categories:
        try:
            response = market_data.get_snapshot(ticker, category)
            price = extract_price(response.json())
        except Exception as exc:
            message = str(exc)
            # Any 401 flavor (bad creds, dead token, missing market-data
            # subscription) won't fix itself this session — disable instead
            # of two failing calls per quote until the next restart.
            if "unauthorized" in message.lower() or "invalid_token" in message.lower():
                global _market_data
                _market_data = None
                if "subscribe" in message.lower():
                    log.error(
                        "Webull says the account lacks a market-data subscription — "
                        "subscribe to stock quotes in the OpenAPI console, then restart. "
                        "Falling back to yfinance."
                    )
                else:
                    log.error("Webull rejected the credentials — disabling Webull quotes until restart")
                return None
            log.warning("Webull snapshot failed for %s/%s: %s", ticker, category, exc)
            continue
        if price is not None:
            _category_cache[ticker] = category
            return price
    return None
