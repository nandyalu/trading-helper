"""The autonomous paper-trading agent.

Once a day, after the sweep has produced signals, this hands the model its own
book — budget, cash, holdings, unrealized P/L — plus the fresh signals and
current prices, and asks it what to trade. What to buy and how much is the
model's decision. Python's job is narrower and non-negotiable: refuse orders
that cannot be executed as stated, and place the rest on the simulated account.

Two things here are easy to get wrong and both would cost real budget:

- **Orders are validated against a running book, not the starting one.** Three
  buys that are each affordable alone are not necessarily affordable together.
  Checking each against the opening cash balance would let all three through
  and overspend by design.
- **The model's arithmetic is never trusted.** It is told the prices and the
  cash; if it proposes a quantity whose cost exceeds what is left, the order is
  dropped, not resized. Resizing would silently turn its decision into a
  different one — see backend/services/analysis.py on the same model inventing
  price levels.

Everything here is blocking (LLM, broker, DB) — call via asyncio.to_thread.
"""
import datetime
import json
import logging
import re
from dataclasses import dataclass, field

from backend.database import db
from backend.services import agent_book, analysis, quotes, sandbox_broker
from backend.services.positions import get_current_price

log = logging.getLogger("trading-bot.agent")

_ENABLED_SETTING_KEY = "agent_enabled"

# How far back to show signals. The trade horizon is 1-2 weeks, so a signal
# older than this has already had its chance and would just crowd the prompt.
_SIGNAL_LOOKBACK_DAYS = 3
_MAX_SIGNALS = 12

# Discord's embed limits, same as backend/services/analysis.py.
_DESCRIPTION_MAX = 4096
_FIELD_MAX = 1024


def is_enabled() -> bool:
    return db.get_setting(_ENABLED_SETTING_KEY) == "on"


def set_enabled(enabled: bool) -> None:
    db.set_setting(_ENABLED_SETTING_KEY, "on" if enabled else "off")


def _recent_signals() -> list:
    cutoff = datetime.date.today() - datetime.timedelta(days=_SIGNAL_LOOKBACK_DAYS)
    return [s for s in db.get_recent_signals(limit=_MAX_SIGNALS) if s.signal_date >= cutoff]


def build_prompt(
    book: agent_book.Book,
    signals: list,
    prices: dict[str, float | None],
    rejected: list[agent_book.Rejection] | None = None,
) -> str:
    """Everything the model gets. Written as plain figures rather than a table
    of jargon, because the numbers are the whole input and a misread one is a
    wrong trade.

    Three things here exist because the model got them wrong on a live run. It
    proposed $1,944 of buys against $1,000 of cash, so the affordable share
    count is now computed in Python and stated per ticker rather than left as
    arithmetic. It treated Hold signals on stocks it did not own as buy
    candidates, so what each decision means is spelled out. And it did not
    realize it could sell to fund a buy, so the ordering rule is stated
    explicitly.

    ``rejected`` carries the reasons a previous attempt's orders were refused,
    turning a hard failure into a correction the model can act on.
    """
    lines = [
        "You manage a small paper-trading account. Decide what to trade today.",
        "",
        f"Your account is ${book.budget:,.2f} in total. That is all you will ever have —",
        "there is no more money coming.",
        f"Of it, ${book.cash:,.2f} is uninvested and available to spend right now.",
        f"Total equity: ${book.equity:,.2f} ({book.return_pct:+.1f}% against the account)",
        f"Realized profit so far: ${book.realized_pnl:,.2f}",
        "",
    ]

    if book.holdings:
        lines.append("You currently hold:")
        for h in book.holdings:
            value = f"${h.market_value:,.2f}" if h.market_value is not None else "unpriced"
            pnl = f"{h.unrealized_pnl:+,.2f}" if h.unrealized_pnl is not None else "unknown"
            price = f"${h.price:,.2f}" if h.price is not None else "unavailable"
            line = (
                f"- {h.ticker}: {h.quantity:g} shares, average cost ${h.avg_cost:,.2f}, "
                f"now {price} each, worth {value}, unrealized {pnl}"
            )
            if h.market_value:
                line += f". Selling all {h.quantity:g} would raise about ${h.market_value:,.2f}"
            lines.append(line)
    else:
        lines.append("You hold nothing. The whole account is in cash.")
    lines.append("")

    if signals:
        lines.append("Recent analyst signals:")
        for s in signals:
            price = prices.get(s.ticker)
            price_text = f"${price:,.2f}" if price is not None else "price unavailable"
            entry = f", suggested entry ${s.entry_price:,.2f}" if s.entry_price else ""
            stop = f", stop ${s.stop_loss:,.2f}" if s.stop_loss else ""
            target = f", target ${s.price_target:,.2f}" if s.price_target else ""
            # Computed here, not left to the model: the affordable count is the
            # arithmetic it actually got wrong.
            if price:
                affordable = int(book.cash // price)
                afford_text = (
                    f" With your ${book.cash:,.2f} cash you can afford {affordable} share(s)."
                    if affordable
                    else f" You cannot afford any at ${price:,.2f} with ${book.cash:,.2f} cash."
                )
            else:
                afford_text = " No price, so it cannot be bought today."
            lines.append(
                f"- {s.ticker} on {s.signal_date}: {s.decision} — now {price_text}"
                f"{entry}{stop}{target}.{afford_text}"
            )
    else:
        lines.append("No new signals today.")

    if rejected:
        lines += [
            "",
            "Your previous answer was refused. Fix it:",
            *(f"- {r.side.upper()} {r.quantity:g} {r.ticker}: {r.why}" for r in rejected),
            "Answer again, within the cash you actually have. If you want something you",
            "cannot afford, sell something first and list the sell before the buy.",
        ]

    lines += [
        "",
        "Rules:",
        f"- The buys you place must cost ${book.cash:,.2f} or less in total, added up "
        "across every buy. Not each — in total.",
        "- Orders execute in the order you list them, so a sell frees its cash for a buy",
        "  listed after it. To buy something you cannot currently afford, sell something",
        "  first and put that sell earlier in the list.",
        "- You may only sell shares you hold. No shorting, no options. Whole shares only.",
        "- What the analysts' decisions mean: Buy means they expect it to rise. Sell means",
        "  they expect it to fall, so exit it if you hold it. Hold means no action is",
        "  recommended — if you do not own it, a Hold is not a reason to buy it.",
        "- Doing nothing is a valid answer, and often the right one.",
        "- Before answering, add up what your buys cost and check it against your cash.",
        "",
        "Reply with JSON only, in this exact shape:",
        '{"reasoning": "one or two sentences", "orders": '
        '[{"ticker": "AAPL", "side": "buy", "quantity": 2, "reason": "why"}]}',
        "Use an empty list for orders if you want to hold everything.",
    ]
    return "\n".join(lines)


def parse_decision(text: str) -> tuple[str, list[dict]]:
    """(reasoning, orders) from the model's reply.

    Tolerant on purpose: this model wraps JSON in prose and code fences often
    enough that a strict parser would throw away usable decisions. Anything
    that still can't be read yields no orders — the agent skips a day, which is
    the safe failure.
    """
    if not text:
        return "", []
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    brace = re.search(r"\{.*\}", candidate, re.S)
    if not brace:
        return "", []
    try:
        payload = json.loads(brace.group(0))
    except ValueError:
        log.warning("Agent reply was not parseable JSON: %s", text[:300])
        return "", []
    if not isinstance(payload, dict):
        return "", []
    orders = payload.get("orders")
    if not isinstance(orders, list):
        orders = []
    return str(payload.get("reasoning") or ""), [o for o in orders if isinstance(o, dict)]


def screen(orders: list[dict], book: agent_book.Book, prices: dict[str, float | None]):
    """Split proposed orders into (accepted, rejected), applying each accepted
    one to a running copy of the book.

    This is the part that must not be simplified into a per-order check against
    the opening balance: three buys that each fit the starting cash do not
    necessarily fit together.
    """
    cash = book.cash
    held = {h.ticker: h.quantity for h in book.holdings}
    accepted: list[dict] = []
    rejected: list[agent_book.Rejection] = []

    for order in orders:
        ticker = str(order.get("ticker", "")).upper().strip()
        running = agent_book.Book(
            budget=book.budget,
            cash=cash,
            realized_pnl=book.realized_pnl,
            holdings=[
                agent_book.Holding(ticker=t, quantity=q, avg_cost=0.0) for t, q in held.items()
            ],
        )
        price = prices.get(ticker)
        rejection = agent_book.validate(order, running, price)
        if rejection is not None:
            rejected.append(rejection)
            continue

        quantity = float(order["quantity"])
        side = str(order["side"]).lower()
        if side == "buy":
            cash -= quantity * price
            held[ticker] = held.get(ticker, 0.0) + quantity
        else:
            # A sell is allowed without a price — you can always exit a
            # position — but unknown proceeds are counted as zero rather than
            # guessed, so they can't fund a later buy in the same pass.
            cash += quantity * price if price is not None else 0.0
            held[ticker] = held.get(ticker, 0.0) - quantity
            if held[ticker] <= 0:
                held.pop(ticker, None)
        accepted.append({**order, "ticker": ticker, "side": side, "quantity": quantity})

    return accepted, rejected


def _price_map(tickers) -> dict[str, float | None]:
    return {ticker: get_current_price(ticker) for ticker in sorted(set(tickers))}


def _ask(prompt: str) -> str:
    response = analysis._quick_think_llm().invoke(
        [
            (
                "system",
                "You are a disciplined paper-trading portfolio manager. You answer "
                "with JSON only — no prose outside it. You never spend more cash "
                "than you have and never sell shares you do not hold.",
            ),
            ("human", prompt),
        ]
    )
    content = response.content
    if isinstance(content, list):
        content = " ".join(str(part) for part in content)
    return str(content)


def _decide(book: agent_book.Book, signals: list, prices: dict[str, float | None]):
    """(reasoning, accepted, rejected), with one correction pass.

    A refused order is information the model never sees otherwise: it proposed
    $1,944 of buys against $1,000 of cash on a live run, and simply dropping the
    overspend threw away whatever it was trying to express. Showing it the
    refusal and asking again lets it either resize or — the case this exists for
    — sell something to fund the buy it wanted.

    Only one retry. If the second answer is still unaffordable, the screened
    subset stands; a loop that keeps arguing with a small model would spend the
    market open doing it. The retry's answer replaces the first wholesale rather
    than merging, because nothing has been placed yet and two half-adopted plans
    are harder to reason about than one.
    """
    reasoning, proposed = parse_decision(_ask(build_prompt(book, signals, prices)))
    accepted, rejected = screen(proposed, book, prices)
    if not rejected:
        return reasoning, accepted, rejected

    log.info("Re-asking after %d refused order(s): %s", len(rejected), [r.why for r in rejected])
    retry_reasoning, retry_proposed = parse_decision(
        _ask(build_prompt(book, signals, prices, rejected=rejected))
    )
    if not retry_proposed:
        # A retry that proposes nothing is a decision to stand pat; keep the
        # first answer's accepted orders rather than discarding them.
        return reasoning, accepted, rejected
    retry_accepted, retry_rejected = screen(retry_proposed, book, prices)
    return retry_reasoning or reasoning, retry_accepted, retry_rejected


@dataclass
class AgentRun:
    """What one pass decided and what came of it."""

    reasoning: str = ""
    placed: list[dict] = field(default_factory=list)
    rejected: list[agent_book.Rejection] = field(default_factory=list)
    failed: list[tuple[dict, str]] = field(default_factory=list)
    book: agent_book.Book | None = None
    skipped: str | None = None  # why the run did nothing at all

    @property
    def acted(self) -> bool:
        return bool(self.placed)


def format_run_embed(run: AgentRun) -> "discord.Embed":
    """What the agent did, for Discord. Rejections are shown, not hidden — a
    decision the model made that could not be executed is the most useful
    thing on the page when the budget is the binding constraint."""
    import discord

    if run.skipped:
        return discord.Embed(
            title="Paper agent — skipped", description=run.skipped, color=discord.Color.greyple()
        )

    book = run.book
    color = discord.Color.blue() if run.acted else discord.Color.greyple()
    embed = discord.Embed(
        title="Paper agent" + (" — traded" if run.acted else " — no trades"),
        description=run.reasoning[:_DESCRIPTION_MAX] or "(no reasoning given)",
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    if book is not None:
        embed.add_field(
            name="Book",
            value=(
                f"Equity **${book.equity:,.2f}** ({book.return_pct:+.1f}% vs "
                f"${book.budget:,.0f} budget)\n"
                f"Cash ${book.cash:,.2f} · invested ${book.invested:,.2f} · "
                f"realized ${book.realized_pnl:+,.2f}"
            ),
            inline=False,
        )

    if run.placed:
        embed.add_field(
            name="Placed",
            value="\n".join(
                f"{o['side'].upper()} {o['quantity']:g} {o['ticker']}"
                + (f" — {o['reason']}" if o.get("reason") else "")
                for o in run.placed
            )[:_FIELD_MAX],
            inline=False,
        )
    if run.rejected:
        embed.add_field(
            name="Rejected",
            value="\n".join(
                f"{r.side.upper()} {r.quantity:g} {r.ticker} — {r.why}" for r in run.rejected
            )[:_FIELD_MAX],
            inline=False,
        )
    if run.failed:
        embed.add_field(
            name="Failed at the broker",
            value="\n".join(
                f"{o['side'].upper()} {o['quantity']:g} {o['ticker']} — {why}"
                for o, why in run.failed
            )[:_FIELD_MAX],
            inline=False,
        )

    embed.set_footer(text="Simulated account — no real money")
    return embed


def settle_pending() -> int:
    """Ask the broker about every order still awaiting a fill and apply the
    answer. Returns how many changed state.

    Run before deciding, so the book the model sees includes last night's
    fills rather than treating them as still-pending cash.
    """
    settled = 0
    for trade in db.get_pending_agent_trades():
        detail = sandbox_broker.get_order_detail(trade.client_order_id)
        if not detail:
            continue
        # Field names verified against a live sandbox fill: status, filled_price,
        # filled_quantity. order_status/avg_fill_price appear in other Webull
        # payloads and are kept as fallbacks, not guesses to rely on.
        status = str(detail.get("status") or detail.get("order_status") or "").upper()
        filled_qty = _as_float(detail.get("filled_quantity"))
        price = _as_float(detail.get("filled_price") or detail.get("avg_fill_price"))
        if status in ("FILLED", "PARTIAL_FILLED") and price and filled_qty:
            db.settle_agent_trade(
                trade.client_order_id,
                status="filled",
                price=price,
                # What actually filled, not what was asked for. A partial fill
                # recorded at the requested size would put shares in the ledger
                # that the account does not hold.
                quantity=filled_qty,
                filled_at=datetime.datetime.now(datetime.timezone.utc),
                broker_order_id=str(detail.get("order_id") or "") or None,
            )
            settled += 1
        elif status in ("CANCELLED", "REJECTED", "FAILED", "EXPIRED"):
            db.settle_agent_trade(trade.client_order_id, status="rejected")
            settled += 1
    return settled


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run_once() -> AgentRun:
    """One decision pass: settle fills, build the book, ask the model, screen
    the answer, place what survives.

    Refuses to run outside the sandbox. sandbox_broker would refuse each order
    anyway, but failing here means the model is never even asked, so a
    misconfigured deployment costs nothing instead of a full analysis.
    """
    if not quotes.is_sandbox():
        return AgentRun(skipped="Webull is not in sandbox mode — refusing to trade.")
    if not is_enabled():
        return AgentRun(skipped="The trading agent is switched off.")

    settled = settle_pending()
    if settled:
        log.info("Settled %d pending order(s) before deciding", settled)

    signals = _recent_signals()
    book = agent_book.build_book(price_lookup=get_current_price)
    prices = _price_map([s.ticker for s in signals] + [h.ticker for h in book.holdings])
    book = agent_book.build_book(price_lookup=prices.get)

    reasoning, accepted, rejected = _decide(book, signals, prices)

    run = AgentRun(reasoning=reasoning, rejected=rejected, book=book)
    signal_by_ticker = {s.ticker: s.id for s in signals}
    for order in accepted:
        try:
            result = sandbox_broker.place_market_order(
                order["ticker"], order["side"].upper(), order["quantity"]
            )
        except Exception as exc:  # broker refusal, network, bad symbol
            log.exception("Order failed for %s", order["ticker"])
            run.failed.append((order, str(exc)))
            continue
        db.record_agent_trade(
            ticker=order["ticker"],
            side=order["side"],
            quantity=order["quantity"],
            client_order_id=result["client_order_id"],
            placed_at=result["placed_at"],
            reason=str(order.get("reason") or "")[:500] or None,
            signal_id=signal_by_ticker.get(order["ticker"]),
        )
        run.placed.append(order)

    # Settle again on the way out, and re-read the book. A market order placed
    # in session hours fills in well under a second, but nothing would notice
    # until the next scheduled pass — so the Discord post and the dashboard
    # would both spend a day reporting cash that has already been spent, beside
    # an order marked "waiting to fill" that filled immediately.
    if run.placed:
        settle_pending()
        run.book = agent_book.build_book(price_lookup=prices.get)
    return run
