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
import time
from dataclasses import dataclass, field

from backend.database import db
from backend.services import agent_book, analysis, candidates, quotes, research, sandbox_broker, watchdog
from backend.services.positions import get_current_price
from backend.services.sizing import get_atr, suggest_position

log = logging.getLogger("trading-bot.agent")

_ENABLED_SETTING_KEY = "agent_enabled"

# The conviction floor: how good a signal has to look before the agent may
# open a position on it. Both default to 0, meaning off, and that default is
# the point rather than caution.
#
# The thresholds read win_probability and risk_reward. The first is the one
# number the model asserts rather than derives, and until the Scorecard's
# calibration says it is honest and that it sorts outcomes, a threshold on it
# is a threshold on a number that may not mean anything — filtering by it would
# feel like discipline while being arbitrary. Turn these on once calibration
# earns it.
_MIN_WIN_PROBABILITY_KEY = "agent_min_win_probability"
_MIN_RISK_REWARD_KEY = "agent_min_risk_reward"

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


def _threshold(key: str) -> float:
    stored = db.get_setting(key)
    try:
        return max(0.0, float(stored)) if stored else 0.0
    except (TypeError, ValueError):
        log.warning("Ignoring unparseable %s %r", key, stored)
        return 0.0


def get_conviction() -> tuple[float, float]:
    """(minimum win probability, minimum risk/reward). Zero means no floor."""
    return _threshold(_MIN_WIN_PROBABILITY_KEY), _threshold(_MIN_RISK_REWARD_KEY)


def set_conviction(min_win_probability: float | None, min_risk_reward: float | None) -> None:
    if min_win_probability is not None:
        if not 0 <= min_win_probability <= 100:
            raise ValueError("Minimum win probability must be between 0 and 100.")
        db.set_setting(_MIN_WIN_PROBABILITY_KEY, str(min_win_probability))
    if min_risk_reward is not None:
        if min_risk_reward < 0:
            raise ValueError("Minimum risk/reward cannot be negative.")
        db.set_setting(_MIN_RISK_REWARD_KEY, str(min_risk_reward))


def fails_conviction(signal, min_probability: float, min_risk_reward: float) -> str | None:
    """Why this signal is not good enough to open a position on, or None.

    A signal that states no probability *fails* a probability floor rather than
    passing it. Asking for at least 60% confidence and accepting a signal that
    claims nothing would make the floor trivially avoidable — the model would
    only have to stop answering the question.

    None as the signal itself means the agent proposed a ticker with no recent
    analysis at all, which is the plainest case a conviction floor exists to
    stop.
    """
    if not min_probability and not min_risk_reward:
        return None
    if signal is None:
        return "no recent signal to justify it"
    if min_probability:
        stated = signal.win_probability
        if stated is None:
            return f"states no win probability (floor is {min_probability:.0f}%)"
        if stated < min_probability:
            return f"{stated:.0f}% win probability is below the {min_probability:.0f}% floor"
    if min_risk_reward:
        stated = signal.risk_reward
        if stated is None:
            return f"states no risk/reward (floor is {min_risk_reward:.2f})"
        if stated < min_risk_reward:
            return f"risk/reward {stated:.2f} is below the {min_risk_reward:.2f} floor"
    return None


def _newest_signal_per_ticker(signals) -> dict:
    """The most recent signal for each ticker.

    Sorts rather than trusting the caller's order. ``get_recent_signals``
    returns newest-first today, but a plain "keep the first one seen" would
    silently invert the moment that changed, and the failure it caused was
    invisible: a stale stop and target are still real levels from a real
    signal, so nothing looks wrong in the ledger or at the broker.

    ``signal_date`` is a date, so two analyses of one ticker on the same day
    tie. ``id`` breaks the tie, and a higher id is the later row.
    """
    newest: dict = {}
    for signal in sorted(signals, key=lambda s: (s.signal_date, s.id or 0)):
        newest[signal.ticker] = signal
    return newest


def _recent_signals() -> list:
    """The signals the agent decides on: recent, and from the model in use.

    The model filter matters as soon as a second one is being evaluated. Every
    signal records which model produced it, so running a comparison sweep puts
    two signals per ticker in the table — sometimes disagreeing — and without
    this the agent would trade on the mix, quietly folding an experiment into
    the live book. It should act on the model the app is configured to use, and
    nothing else.

    Signals from before the model column existed carry NULL and are kept: they
    are real track record, they just cannot be attributed.
    """
    cutoff = datetime.date.today() - datetime.timedelta(days=_SIGNAL_LOOKBACK_DAYS)
    configured = analysis.get_model()
    return [
        s
        for s in db.get_recent_signals(limit=_MAX_SIGNALS * 3)
        if s.signal_date >= cutoff and (s.model is None or s.model == configured)
    ][:_MAX_SIGNALS]


# How many past trades to show individually. Enough to see a pattern, few
# enough that the list does not crowd out today's actual decision.
_HISTORY_SHOWN = 6


def describe_history(closed: list) -> list[str]:
    """The agent's own track record, in its own prompt.

    Without this it wakes every morning with a book and no idea that the last
    four things it bought on a Hold signal all lost money. A model that cannot
    see its outcomes cannot avoid repeating them, and neither can you tell
    whether it is learning.

    Returns [] on an empty record rather than a line saying so — "you have made
    no trades" is noise on day one, and the holdings section already says the
    book is empty.
    """
    if not closed:
        return []
    wins = sum(1 for t in closed if t.won)
    net = sum(t.pnl for t in closed)
    held = sum(t.held_days for t in closed) / len(closed)
    lines = [
        f"How your own past trades turned out — {len(closed)} closed, {wins} profitable, "
        f"{net:+,.2f} net, held {held:.0f} days on average:",
    ]
    for trade in closed[-_HISTORY_SHOWN:]:
        origin = f" (analyst said {trade.signal_decision})" if trade.signal_decision else ""
        lines.append(
            f"- {trade.ticker}: bought ${trade.entry:,.2f}, sold ${trade.exit:,.2f}, "
            f"{trade.return_pct:+.1f}% over {trade.held_days} day(s){origin}"
        )

    # The pattern most worth naming: this model bought a stock whose only signal
    # was Hold, and put 98% of the budget into it.
    on_hold = [t for t in closed if (t.signal_decision or "").lower() == "hold"]
    if len(on_hold) >= 2:
        hold_wins = sum(1 for t in on_hold if t.won)
        lines.append(
            f"Of the {len(on_hold)} you bought on a Hold signal, {hold_wins} made money."
        )
    return lines


def build_prompt(
    book: agent_book.Book,
    signals: list,
    prices: dict[str, float | None],
    rejected: list[agent_book.Rejection] | None = None,
    closed: list[agent_book.ClosedTrade] | None = None,
    regime_line: str | None = None,
    horizon_days: int | None = None,
    menu: list | None = None,
    price: float = 0.0,
    max_research: int = 0,
    watchlist: list[str] | None = None,
    max_watchlist: int = 0,
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
    ]
    if regime_line:
        lines += [regime_line, ""]
    lines += [
        f"Your account is ${book.budget:,.2f} in total. That is all you will ever have —",
        "there is no more money coming.",
        f"Of it, ${book.cash:,.2f} is uninvested and available to spend right now.",
        f"Total equity: ${book.equity:,.2f} ({book.return_pct:+.1f}% against the account)",
        f"Realized profit so far: ${book.realized_pnl:,.2f}",
        "",
    ]

    if book.holdings:
        lines.append("You currently hold:")
        exits_by_ticker = {
            h.ticker: {
                t.exit_kind: t.limit_price
                for t in db.get_resting_exits(h.ticker)
                if t.exit_kind and t.limit_price
            }
            for h in book.holdings
        }
        for h in book.holdings:
            value = f"${h.market_value:,.2f}" if h.market_value is not None else "unpriced"
            pnl = f"{h.unrealized_pnl:+,.2f}" if h.unrealized_pnl is not None else "unknown"
            # Named apart from the `price` parameter deliberately. Reusing it
            # here rebound the research price to a string, and the menu block
            # below then formatted that string as a float. The crash needed a
            # holding and a menu together, so it was invisible until the agent
            # first bought something.
            price_each = f"${h.price:,.2f}" if h.price is not None else "unavailable"
            line = (
                f"- {h.ticker}: {h.quantity:g} shares, average cost ${h.avg_cost:,.2f}, "
                f"now {price_each} each, worth {value}, unrealized {pnl}"
            )
            weight = book.weight_pct(h)
            if weight is not None:
                line += f", {weight:.0f}% of the account"
            held_days = h.held_days()
            if held_days is not None:
                line += f", held {held_days} day(s)"
            # What is actually resting at the broker on this position. Without
            # it the model cannot tell an exit it should move from one that is
            # already where it wants it — or notice there is none at all.
            resting = exits_by_ticker.get(h.ticker, {})
            if resting:
                levels = ", ".join(
                    f"{kind} at ${level:,.2f}" for kind, level in sorted(resting.items())
                )
                line += f". Currently protected by a resting {levels}"
            else:
                line += ". NOTHING is resting to close it"
            if h.market_value:
                line += f". Selling all {h.quantity:g} would raise about ${h.market_value:,.2f}"
            lines.append(line)
    else:
        lines.append("You hold nothing. The whole account is in cash.")
    lines.append("")

    if signals:
        lines.append("Recent analyst signals:")
        for s in signals:
            # Also kept off `price`, for the same reason as the holdings loop.
            live = prices.get(s.ticker)
            price_text = f"${live:,.2f}" if live is not None else "price unavailable"
            entry = f", suggested entry ${s.entry_price:,.2f}" if s.entry_price else ""
            stop = f", stop ${s.stop_loss:,.2f}" if s.stop_loss else ""
            target = f", target ${s.price_target:,.2f}" if s.price_target else ""
            # How good the analyst thought the bet was, not merely which way it
            # pointed. Without these every Buy reads as equally good and the
            # choice between them comes down to what happens to be affordable.
            conviction = ""
            if s.win_probability is not None:
                conviction += f", {s.win_probability:.0f}% chance of working"
            if s.risk_reward is not None:
                conviction += f", risk/reward {s.risk_reward:.1f} to 1"
            if s.expected_value_r is not None:
                conviction += f", expected value {s.expected_value_r:+.2f}R"
            # Computed here, not left to the model: the affordable count is the
            # arithmetic it actually got wrong.
            if live:
                # Floor division on a negative balance returns -1, not 0, and
                # -1 is truthy — so a book at minus $8.00 was told "you can
                # afford -1 share(s)" on every signal line. Clamped, and the
                # branch now tests for a positive count rather than a non-zero
                # one, because those differ only when the answer is nonsense.
                affordable = max(0, int(book.cash // live))
                afford_text = (
                    f" With your ${book.cash:,.2f} cash you can afford {affordable} share(s)."
                    if affordable > 0
                    else f" You cannot afford any at ${live:,.2f} with ${book.cash:,.2f} cash."
                )
            else:
                afford_text = " No price, so it cannot be bought today."
            lines.append(
                f"- {s.ticker} on {s.signal_date}: {s.decision} — now {price_text}"
                f"{entry}{stop}{target}{conviction}.{afford_text}"
            )
    else:
        lines.append("No new signals today.")

    history = describe_history(closed or [])
    if history:
        lines += ["", *history]

    if rejected:
        lines += [
            "",
            "Your previous answer was refused. Fix it:",
            *(f"- {r.side.upper()} {r.quantity:g} {r.ticker}: {r.why}" for r in rejected),
            "Answer again, within the cash you actually have. If you want something you",
            "cannot afford, sell something first and list the sell before the buy.",
            # The retry is the one chance to correct a refusal, and advice about
            # cash does not help a watchlist refusal. Observed on the first live
            # probe: the model asked to research two names without untracking
            # anything, which is exactly the mistake this line answers.
            *(
                ["If a research was refused because the watchlist is full, untrack "
                 "something first and list the untrack before the research."]
                if any(r.side == "research" and "watchlist is full" in r.why for r in rejected)
                else []
            ),
        ]

    # What "no money" means here is what screen() refuses at: below the research
    # price nothing can be commissioned, and below a share price nothing can be
    # bought. The research price is the lower of the two and the one this app
    # controls, so it is the threshold the prompt speaks about.
    research_price_floor = price if price else 0.01

    min_probability, min_risk_reward = get_conviction()
    floors = []
    if min_probability:
        floors.append(f"at least {min_probability:.0f}% chance of working")
    if min_risk_reward:
        floors.append(f"risk/reward of at least {min_risk_reward:.2f}")
    conviction_line = " and ".join(floors)

    if watchlist and max_watchlist:
        # Shown before the menu, because what is already being paid for every
        # morning is the context for whether to add another. Held names are
        # separated from watched-only ones because only the second kind can be
        # dropped, and a list that hides that invites orders Python refuses.
        held_tickers = {h.ticker for h in book.holdings}
        watched_only = sorted(t for t in watchlist if t not in held_tickers)
        also_held = sorted(t for t in watchlist if t in held_tickers)
        # The daily cost as a figure, not as two facts to multiply. The price
        # appears in the menu section and the count appears here, and across
        # five passes the agent never once mentioned the watchlist — while
        # writing that it had "small cash amount available for new shares".
        # This app already computes the affordable-share count in Python for
        # the same reason: a model left to do the arithmetic proposed $1,944 of
        # buys against $1,000 of cash.
        daily = len(watchlist) * price
        droppable_cost = len(watched_only) * price
        cost_line = (
            f"You are paying ${daily:,.2f} every morning to have "
            f"{len(watchlist)} tickers analysed, and you may track at most "
            f"{max_watchlist}." if price else
            f"You are paying to have {len(watchlist)} tickers analysed every "
            f"morning, and you may track at most {max_watchlist}."
        )
        lines += ["", cost_line]
        if also_held:
            lines.append(
                f"- Held, so always analysed and cannot be dropped: {', '.join(also_held)}"
            )
        if watched_only:
            saving = (f", and dropping them all would save ${droppable_cost:,.2f} a day"
                      if price else "")
            lines.append(
                f"- Watched but not held, so droppable: {', '.join(watched_only)}"
                f"{saving}"
            )
        if len(watchlist) >= max_watchlist:
            lines.append(
                "That is the limit, so nothing new can be researched until you stop "
                "watching something."
            )

    if menu:
        lines += [
            "",
            f"You may pay ${price:,.2f} to have a stock analysed. That money comes out of the "
            f"same cash you trade with, so it is a real cost and a bad choice of what to "
            f"study is a loss like any other. You may research at most {max_research} today.",
            "",
            "Nothing has been analysed on these yet — they are screened for being liquid and "
            "actively traded, not for being good. Researching one buys you an analyst's "
            "opinion tomorrow, not a position today:",
        ]
        for candidate in menu:
            move = f", {candidate.change_pct:+.1f}% today" if candidate.change_pct is not None else ""
            lines.append(
                f"- {candidate.ticker}: {candidate.name[:40]} at ${candidate.price:,.2f}"
                f"{move}, {candidate.volume_m:,.1f}M shares traded"
            )
        lines.append(
            "Anything you already hold is analysed every day whether you ask or not, and "
            "charged the same — you own the cost of finding your own exit."
        )

    lines += [
        "",
        "Rules:",
        # A balance at or below zero used to render as "must cost $-8.00 or
        # less in total", which is not an instruction anybody can follow. State
        # the condition, what it prevents, and what changes it.
        *(
            [
                f"- **You have no money to spend. The balance is ${book.cash:,.2f}.** You",
                "  cannot buy anything and cannot pay for a new analysis until that",
                "  changes. Selling is the only thing that raises cash.",
                "- The analyses you already pay for run and are charged tomorrow whether",
                "  or not there is money for them, so this gets worse on its own.",
                "  Untracking raises no cash and stops part of the charge.",
            ]
            if book.cash < research_price_floor
            else [
                f"- The buys you place must cost ${book.cash:,.2f} or less in total, added up "
                "across every buy. Not each — in total.",
            ]
        ),
        "- Orders execute in the order you list them, so a sell frees its cash for a buy",
        "  listed after it. To buy something you cannot currently afford, sell something",
        "  first and put that sell earlier in the list.",
        "- You may only sell shares you hold. No shorting, no options. Whole shares only.",
        "- What the analysts' decisions mean: Buy means they expect it to rise. Sell means",
        "  they expect it to fall, so exit it if you hold it. Hold means no action is",
        "  recommended — if you do not own it, a Hold is not a reason to buy it.",
        "- Some signals carry how good the analyst thought the bet was. The chance of",
        "  working is their own estimate. Risk/reward compares what is gained if the",
        "  target is reached against what is lost if the stop is hit. Expected value is",
        "  in R-multiples, where one R is the amount risked: positive means the bet pays",
        "  at the stated odds, negative means it does not. Signals without these numbers",
        "  are not worse bets, only ones where the analyst did not say.",
        *(
            [
                f"- You may only open a new position on a signal that meets the conviction "
                f"floor: {conviction_line}. A signal below it, or one that does not state "
                "the number, cannot be bought. Selling is never blocked this way.",
            ]
            if conviction_line
            else []
        ),
        "- You can also move the stop and take-profit on something you already hold,",
        "  without buying or selling any of it. Use side \"adjust\" with a \"stop\" or a",
        "  \"target\" price, or both. The stop must be below the current price and the",
        "  target above it, or the order would execute the moment it was placed.",
        "  Raising a stop as a position gains is how a profit is protected; today's",
        "  analysis is what tells you where the thesis now breaks. If a holding has",
        "  nothing resting on it, an adjust places the exits for the first time.",
        *(
            [
                "- To have something analysed, use side \"research\" with a ticker from the",
                "  list above and no quantity. You will see the analyst's answer tomorrow and",
                "  can decide then. Choosing what to study is the only way anything new ever",
                "  enters this account, and paying to study something you then ignore is how",
                "  the money leaves it.",
            ]
            if menu
            else []
        ),
        *(
            [
                f"- You may track at most {max_watchlist} tickers, and every one of them is",
                "  analysed and charged every morning whether you act on it or not. To stop",
                "  watching one, use side \"untrack\" with its ticker and no quantity.",
                "  Untracking costs nothing and refunds nothing — what it saves is the",
                "  analyses you would have paid for tomorrow and after.",
                "- Untracking frees a slot the same way a sell frees cash, and in the same",
                "  order: to research something when the list is full, list the untrack",
                "  first and the research after it.",
                "- You cannot untrack something you hold. Sell it first if it is genuinely",
                "  not worth analysing — a position nobody is analysing is one with nothing",
                "  watching for its exit.",
            ]
            if max_watchlist
            else []
        ),
        "- Doing nothing is a valid answer, and often the right one.",
        *(
            [
                f"- These are meant to be {horizon_days}-day trades. A position held much",
                "  longer than that has outlived the thesis it was opened on, whether or",
                "  not anything has told you to sell it.",
            ]
            if horizon_days
            else []
        ),
        "- Before answering, add up what your buys cost and check it against your cash.",
        "",
        "Reply with JSON only, in this exact shape:",
        '{"reasoning": "one or two sentences", "orders": '
        '[{"ticker": "AAPL", "side": "buy", "quantity": 2, "reason": "why"},',
        # The untrack example appears only where untracking is possible. The
        # live deployment has no cap and no such action, and an example of an
        # order it can only have refused would cost it a retry to learn that.
        (' {"ticker": "MSFT", "side": "adjust", "stop": 410.5, "reason": "why"},'
         if max_watchlist
         else ' {"ticker": "MSFT", "side": "adjust", "stop": 410.5, "reason": "why"}]}'),
        *([' {"ticker": "NOK", "side": "untrack", "reason": "why"}]}'] if max_watchlist else []),
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


def screen(
    orders: list[dict],
    book: agent_book.Book,
    prices: dict[str, float | None],
    signals_by_ticker: dict | None = None,
    menu: set[str] | None = None,
):
    """Split proposed orders into (accepted, rejected), applying each accepted
    one to a running copy of the book.

    This is the part that must not be simplified into a per-order check against
    the opening balance: three buys that each fit the starting cash do not
    necessarily fit together.

    The conviction floor is enforced here rather than by leaving low-conviction
    signals out of the prompt. The agent still needs to see them — a Sell it
    has no confidence in is still a reason to close a position it holds — so
    the floor applies to opening a position, not to knowing about one. And it
    is checked in Python for the same reason every other limit is: a rule
    stated only in the prompt is a request, not a limit.

    A floor of zero, which is the default, skips the check entirely.
    """
    min_probability, min_risk_reward = get_conviction()
    # Research is spent from the same cash as the trades, and it is spent
    # first: a buy listed after it must see the money already gone, or the
    # agent could commit the same dollar twice.
    research_price = research.get_price()
    max_research = _max_research_per_day()
    max_watchlist = _max_watchlist()
    researched: list[str] = []
    untracked: list[str] = []
    # A running watchlist, not the opening one, for the same reason cash is
    # running: an untrack listed before a research frees a slot for it in the
    # same pass, and two researches against one free slot must not both pass.
    watchlist = set(db.get_watchlist())
    cash = book.cash
    held = {h.ticker: h.quantity for h in book.holdings}
    accepted: list[dict] = []
    rejected: list[agent_book.Rejection] = []

    for order in orders:
        ticker = str(order.get("ticker", "")).upper().strip()
        if str(order.get("side", "")).lower().strip() == "research":
            # Neither a buy nor a sell: it moves cash but no shares, and what
            # it buys is an opinion tomorrow rather than a position today.
            why = None
            if menu is not None and ticker not in menu:
                why = "not on today's candidate list"
            elif ticker in watchlist:
                why = "already being researched today"
            elif len(researched) >= max_research:
                why = f"the daily research limit of {max_research} is reached"
            elif len(watchlist) >= max_watchlist:
                # Named as a swap rather than a wall, because it is one: an
                # untrack listed earlier in the same answer would have made
                # room. The prompt says so too; this is what it reads like
                # when the agent has not done it.
                why = (
                    f"the watchlist is full at {max_watchlist} — untrack something "
                    "first, and list the untrack before this"
                )
            elif cash < research_price:
                why = f"costs ${research_price:,.2f} and only ${cash:,.2f} is left"
            if why:
                rejected.append(
                    agent_book.Rejection(ticker=ticker, side="research", quantity=0, why=why)
                )
                continue
            cash -= research_price
            researched.append(ticker)
            watchlist.add(ticker)
            accepted.append({**order, "ticker": ticker, "side": "research", "quantity": 0})
            continue

        if str(order.get("side", "")).lower().strip() == "untrack":
            # Moves no cash and no shares. What it changes is what tomorrow's
            # sweep spends GPU time on, which is why it exists: research adds
            # to the watchlist permanently and nothing else here removes.
            why = None
            if ticker not in watchlist:
                why = "not being watched, so there is nothing to stop watching"
            elif held.get(ticker, 0.0) > 0:
                # Enforced here rather than asked for in the prompt, like every
                # other limit that must hold. A position whose daily analysis
                # stops is a position with nothing looking for its exit, and
                # the analysis of a holding is what the charge already pays
                # for. Sell it first if it is genuinely not worth watching.
                why = (
                    f"holds {held[ticker]:g} of it — sell it first, since a position "
                    "you stop analysing is one with nothing watching for its exit"
                )
            if why:
                rejected.append(
                    agent_book.Rejection(ticker=ticker, side="untrack", quantity=0, why=why)
                )
                continue
            watchlist.discard(ticker)
            untracked.append(ticker)
            accepted.append({**order, "ticker": ticker, "side": "untrack", "quantity": 0})
            continue

        if str(order.get("side", "")).lower().strip() == "adjust":
            # Moves no cash and no shares, so the running-balance machinery
            # below has nothing to say about it. What it does need is a
            # position to rest on.
            quantity_held = held.get(ticker, 0.0)
            if quantity_held <= 0:
                rejected.append(
                    agent_book.Rejection(
                        ticker=ticker, side="adjust", quantity=0,
                        why="holds none of it, so there are no exits to move",
                    )
                )
                continue
            if order.get("stop") is None and order.get("target") is None:
                rejected.append(
                    agent_book.Rejection(
                        ticker=ticker, side="adjust", quantity=0,
                        why="no new stop or target given",
                    )
                )
                continue
            accepted.append(
                {**order, "ticker": ticker, "side": "adjust", "quantity": quantity_held}
            )
            continue
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
            why = fails_conviction(
                (signals_by_ticker or {}).get(ticker), min_probability, min_risk_reward
            )
            if why is not None:
                rejected.append(
                    agent_book.Rejection(ticker=ticker, side=side, quantity=quantity, why=why)
                )
                continue
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


def current_regime_line() -> str | None:
    """One line of market context — VIX, SPY against its 200-day, the yield
    curve — already computed for the 12:45 post.

    How aggressively to deploy cash is exactly the kind of judgement this
    should inform, and the numbers were being thrown away every morning. Best
    effort: a failed fetch drops the line rather than the decision.
    """
    from backend.services import regime

    try:
        data = regime.fetch_regime()
        label, emoji = regime.classify_regime(
            data.vix, data.spy_vs_ma_pct, data.curve_spread_pct
        )
    except Exception:
        log.warning("Couldn't read the market regime for the agent prompt", exc_info=True)
        return None
    line = f"Market conditions today: {label}."
    if data.vix is not None:
        line += f" VIX {data.vix:.1f}."
    if data.spy_vs_ma_pct is not None:
        line += f" The S&P is {data.spy_vs_ma_pct:+.1f}% against its 200-day average."
    return line


def _horizon_days() -> int | None:
    """How long a position is meant to be held, from the configured horizon."""
    from backend.services.signals import horizon_params

    try:
        return horizon_params(analysis.get_horizon())["eval_days"]
    except Exception:
        return None


def _price_map(tickers) -> dict[str, float | None]:
    return {ticker: get_current_price(ticker) for ticker in sorted(set(tickers))}


# Lifted out of _ask so it can be hashed alongside the rest of the prompt.
# A change here changes the agent's behaviour as surely as a change to the
# rules, and an experiment that cannot tell which prompt produced which
# decision cannot attribute a change in behaviour to anything.
SYSTEM_PROMPT = (
    "You are a disciplined paper-trading portfolio manager. You answer "
    "with JSON only — no prose outside it. You never spend more cash "
    "than you have and never sell shares you do not hold."
)


def _ask(prompt: str) -> str:
    response = analysis._quick_think_llm().invoke(
        [("system", SYSTEM_PROMPT), ("human", prompt)]
    )
    content = response.content
    if isinstance(content, list):
        content = " ".join(str(part) for part in content)
    return str(content)


def _decide(book, signals, prices, closed=None, regime_line=None, horizon_days=None, menu=None):
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
    by_ticker = {s.ticker: s for s in signals}
    menu_tickers = {c.ticker for c in menu} if menu else None
    # Read once and passed to both attempts, so the retry describes the same
    # watchlist the first answer was screened against.
    watchlist = sorted(db.get_watchlist())
    # The exact prompt, kept so the Events page can show what was asked. A
    # retry replaces it, because the retry is the prompt the accepted orders
    # were actually screened from.
    shown = build_prompt(
        book, signals, prices, closed=closed, regime_line=regime_line,
        horizon_days=horizon_days, menu=menu, price=research.get_price(),
        max_research=_max_research_per_day(),
        watchlist=watchlist, max_watchlist=_max_watchlist(),
    )
    answer = _ask(shown)
    reasoning, proposed = parse_decision(answer)
    accepted, rejected = screen(proposed, book, prices, by_ticker, menu_tickers)
    if not rejected:
        return Decision(reasoning, accepted, rejected, shown, answer)

    log.info("Re-asking after %d refused order(s): %s", len(rejected), [r.why for r in rejected])
    shown = build_prompt(book, signals, prices, rejected=rejected, closed=closed,
                         regime_line=regime_line, horizon_days=horizon_days, menu=menu,
                         price=research.get_price(), max_research=_max_research_per_day(),
                         watchlist=watchlist, max_watchlist=_max_watchlist())
    retry_answer = _ask(shown)
    retry_reasoning, retry_proposed = parse_decision(retry_answer)
    if not retry_proposed:
        # A retry that proposes nothing is a decision to stand pat; keep the
        # first answer's accepted orders rather than discarding them.
        return Decision(reasoning, accepted, rejected, shown, retry_answer)
    retry_accepted, retry_rejected = screen(retry_proposed, book, prices, by_ticker, menu_tickers)
    return Decision(retry_reasoning or reasoning, retry_accepted, retry_rejected,
                    shown, retry_answer)


@dataclass
class Decision:
    """One decision pass: what was asked, what came back, and what survived.

    ``prompt`` and ``response`` are kept verbatim because the counts and the
    one-line reasoning describe a decision while these two *are* it. Behaviour
    here is mostly prompt, so a month of runs across three prompt revisions
    cannot be told apart afterwards without them.
    """

    reasoning: str
    accepted: list[dict]
    rejected: list
    prompt: str = ""
    response: str = ""

    def __iter__(self):
        """Unpack like the tuple this replaced, so existing callers and tests
        that write ``reasoning, accepted, rejected = _decide(...)`` keep
        working."""
        return iter((self.reasoning, self.accepted, self.rejected))


@dataclass
class AgentRun:
    """What one pass decided and what came of it."""

    reasoning: str = ""
    placed: list[dict] = field(default_factory=list)
    rejected: list[agent_book.Rejection] = field(default_factory=list)
    failed: list[tuple[dict, str]] = field(default_factory=list)
    # Exits moved to new levels. Kept apart from placed: no position was
    # opened or closed, but the risk on an open one changed, which is worth
    # reporting rather than folding into "no trades".
    adjusted: list[str] = field(default_factory=list)
    # Tickers it paid to have analysed. Not a trade — the position it may or
    # may not take is tomorrow's decision — but money left the account, so a
    # pass that only researched is not an idle pass.
    researched: list[str] = field(default_factory=list)
    # Tickers it stopped watching. No money moves either way, but tomorrow's
    # sweep is smaller for it, so this is a decision and not housekeeping.
    untracked: list[str] = field(default_factory=list)
    book: agent_book.Book | None = None
    skipped: str | None = None  # why the run did nothing at all
    # The words, kept for the Events page. Empty on a pass that never asked —
    # a skipped run, or one the market was shut for.
    prompt: str = ""
    response: str = ""

    @property
    def acted(self) -> bool:
        return bool(self.placed or self.adjusted or self.researched or self.untracked)


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
    if run.adjusted:
        embed.add_field(
            name="Exits moved",
            value="\n".join(run.adjusted)[:_FIELD_MAX],
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


# How many analyses the agent may commission in one day, whatever it can
# afford. Money does not model time: the sweep has to finish before the open,
# and an agent with cash to burn could otherwise queue more GPU-hours than
# there are hours.
_MAX_RESEARCH_PER_DAY = 15


def _max_research_per_day() -> int:
    return _MAX_RESEARCH_PER_DAY


# How many tickers may be tracked at once. This is the limit that actually
# binds, and the daily cap above does not substitute for it: research adds to
# the watchlist permanently, so a per-day limit bounds the rate of growth and
# not the total, the same way a daily spending limit does not stop a
# subscription.
#
# The number comes from the sweep window. morning_sweep runs at 11:00 UTC and
# earnings_check puts its own analyses on the same pool at 13:00, so there are
# two hours. At three concurrent analyses and gemma4:e4b-it-qat's 17.4 minutes
# — the paired figure, because analyses really do run together — that window
# fits about 20 tickers with nothing going wrong. Twelve is four waves and
# leaves the second hour for a slow run, a retry, or a morning when the live
# deployment is contending for the same cards.
#
# Raise it only alongside the arithmetic: a faster model, more backends, or an
# earlier sweep. Raising it because the agent keeps asking is how a sweep comes
# to overrun the open.
#
# **Due for re-derivation when the pool splits 2/5 instead of 4/3**, which is
# planned once the Gemini Flash-Lite comparison reports. Five concurrent
# analyses is not 5/3 of three: gemma4's E-series keeps its per-layer
# embeddings in host RAM, so the cards contend for memory bandwidth and the
# per-analysis time rises with the count. Measure the paired figure again at
# five before choosing the number rather than scaling this one.
_MAX_WATCHLIST = 12


def _max_watchlist() -> int:
    return _MAX_WATCHLIST


# How many screened names to show. Enough to choose from, few enough that the
# list does not crowd out the holdings and signals above it — and every extra
# line is prompt tokens on every pass, whether or not anything is researched.
_MENU_SIZE = 15


def _candidate_menu() -> list:
    """Screened names the agent may pay to have analysed.

    Never free-form. A model naming its own tickers invents symbols, reaches
    illiquid things with no price data, and picks the day's pump — a raw screen
    once returned a stock up 927%, which the price floor alone does not catch
    because the pump is what lifted the price over the floor. candidates.py
    already filters for liquidity and excludes anything up more than 30%.
    """
    try:
        found = candidates.fetch_candidates()
    except Exception:
        log.exception("Could not screen for candidates — the agent decides without a menu")
        return []
    return found[:_MENU_SIZE]


def _place(
    order: dict,
    price: float | None,
    stops: dict[str, float],
    targets: dict[str, float],
) -> dict:
    """Place one accepted order, as a bracket where that is possible.

    A bracket submits the buy and its exits together and the broker activates
    the exits itself the moment the entry fills, so there is no window in which
    the shares are owned and nothing is protecting them. Arming afterwards
    always had that window, however short the wait for the fill.

    It is not always possible, and the fallback is not a formality:

    - a sell is never bracketed — it *is* the exit;
    - a buy with no usable level has nothing to bracket with;
    - and a combo is refused outright while the cash is unsettled, which is
      routine here, because selling to fund a buy in the same pass is
      something the agent is explicitly told it can do.

    So a refused bracket falls back to the plain market order rather than
    failing the trade. The position is then armed the slower way, which is the
    behaviour this replaced and is still correct — just briefly exposed.
    """
    ticker = order["ticker"]
    if order["side"] != "buy":
        return sandbox_broker.place_market_order(ticker, order["side"].upper(), order["quantity"])

    stop, target = usable_levels(ticker, stops.get(ticker), targets.get(ticker), price)
    if stop is None and price:
        stop = atr_stop(ticker, price)
    if price and (stop or target):
        try:
            return sandbox_broker.place_bracket_order(
                ticker, order["quantity"], price, stop, target
            )
        except Exception as exc:
            log.warning(
                "Bracket refused for %s (%s) — buying at market and arming separately",
                ticker, str(exc)[:200],
            )

    return sandbox_broker.place_market_order(ticker, "BUY", order["quantity"])


def _record_unguarded(ticker: str, quantity: float, why: str) -> None:
    """Write down that a position was opened with nothing protecting it.

    Until this existed the failure was completely silent: no ledger row, no
    alert, no Discord line. Two positions sat unguarded for days on
    2026-08-20 and the only reason anyone found out was a person noticing the
    broker screen — by then the run's logs had been erased with the container,
    so *why* the exits never rested had to be reconstructed from prices.

    Recorded as an alert rather than a trade, because nothing was traded. The
    watchdog's alert table is already the place the dashboard reads for things
    that need a person.
    """
    log.error("%s is unguarded: %s", ticker, why)
    try:
        db.record_alert(
            ticker=ticker,
            alert_type="unguarded_position",
            # Once per ticker per day. The same position stays unguarded until
            # someone acts on it, and re-announcing it every pass would bury
            # the alert that is still new.
            dedupe_key=f"unguarded:{ticker}:{datetime.date.today().isoformat()}",
            message=f"{quantity:g} share(s) of {ticker} have no resting exit — {why}",
        )
    except Exception:
        # An unrecordable alert must not undo a filled buy.
        log.exception("Couldn't record the unguarded-position alert for %s", ticker)


def atr_stop(ticker: str, price: float) -> float | None:
    """A stop derived from the stock's own volatility, for a buy whose stated
    stop cannot be used.

    Every position needs an exit, and the signal's stop is missing more often
    than it looks. ``_resolve_stop_loss`` already substitutes this at
    signal-record time — but only for Buy and Overweight, and the agent buys on
    Hold signals too. A Hold therefore carries whatever the trader stated and
    no safety net, and days can pass between the signal and the purchase.

    That gap is what went wrong on 2026-08-18 and 2026-08-19. NOK was bought at
    $10.47 against a $10.56 stop and INTC at $91.84 against a $94.00 stop —
    both stocks had fallen through their own stop in the meantime, so the level
    was discarded as unusable and the position opened with nothing under it.

    Derived from the price at purchase rather than at the signal, and 2×ATR
    below it by construction, so it cannot come back on the wrong side.
    """
    atr = get_atr(ticker)
    if atr is None:
        log.warning("No ATR for %s — cannot derive a stop", ticker)
        return None
    suggestion = suggest_position(price, atr)
    if suggestion is None or suggestion.stop is None or suggestion.stop >= price:
        return None
    log.info(
        "Using an ATR-derived stop of %.2f for %s at %.2f — the stated stop was unusable",
        suggestion.stop, ticker, price,
    )
    return suggestion.stop


def _record_exits(ticker: str, exits: list[dict]) -> None:
    """Ledger rows for exits the broker is already holding.

    Separate from ``_arm_exits`` because there is nothing to arm: these legs
    were submitted with the buy and the broker activates them on the fill. All
    that is left is to write down what is resting, so the dashboard and the
    settlement pass can see it.
    """
    for leg in exits:
        label = "stop-loss" if leg["kind"] == "stop" else "take-profit"
        db.record_agent_trade(
            ticker=ticker,
            side="sell",
            quantity=leg.get("quantity") or 0,
            client_order_id=leg["client_order_id"],
            placed_at=leg["placed_at"],
            reason=f"{label} resting at ${leg['price']:,.2f}",
            signal_id=None,
            is_stop=True,
            limit_price=leg["price"],
            exit_kind=leg["kind"],
        )
    log.info(
        "Bracketed %s with %s",
        ticker, ", ".join(f"{l['kind']} {l['price']:,.2f}" for l in exits),
    )


def _cancel_resting_exits(ticker: str) -> int:
    """Cancel every resting exit on a ticker the agent is selling.

    An exit left behind after the position closes is not merely untidy: it is a
    live order to sell shares that are no longer owned, which the broker would
    either reject later or fill into a short.
    """
    cancelled = 0
    for trade in db.get_pending_agent_trades():
        if not trade.is_stop or trade.ticker != ticker:
            continue
        if sandbox_broker.cancel_order(trade.client_order_id):
            db.settle_agent_trade(trade.client_order_id, status="rejected")
            cancelled += 1
    if cancelled:
        log.info("Cancelled %d resting exit(s) on %s", cancelled, ticker)
    return cancelled


def usable_levels(
    ticker: str, stop_price: float | None, target_price: float | None, price: float | None
) -> tuple[float | None, float | None]:
    """Drop the exit levels that would execute the instant they exist.

    A limit sell below the market fills at market, and a stop above it triggers
    at once. Either liquidates the position the moment it is opened — and the
    take-profit would be announced as a profit while booking a loss. Not
    hypothetical: a live signal produced a $95.96 target on a stock trading at
    $97.57.

    An unknown price is not evidence against a level, so nothing is dropped
    when the quote is missing.
    """
    if price is None:
        return stop_price, target_price
    if stop_price is not None and stop_price >= price:
        log.warning(
            "Refusing a stop at %.2f on %s trading at %.2f — it would trigger at once",
            stop_price, ticker, price,
        )
        stop_price = None
    if target_price is not None and target_price <= price:
        log.warning(
            "Refusing a target at %.2f on %s trading at %.2f — it would fill at once",
            target_price, ticker, price,
        )
        target_price = None
    return stop_price, target_price


# How long to wait for a buy to fill before arming its exits, and how often to
# ask. A market order in session hours fills in well under a second; this is
# generous enough to cover a slow one without holding the decision pass open.
_FILL_WAIT_SECONDS = 20
_FILL_POLL_SECONDS = 2


def _await_fill(client_order_id: str) -> bool:
    """Block until the buy has actually filled, or give up.

    Exits cannot be placed before the shares exist. A cash account counts every
    resting sell against the position it can see, so a stop and a take-profit
    for three shares each, placed while the buy is still submitted, read as six
    shares sold against nothing — the broker refuses the pair outright with
    GENERATE_NEW_SHORT_POSITION. That is exactly what happened on 2026-08-13:
    both buys filled and neither got its exits, because arming ran milliseconds
    after the order was sent rather than after it was done.
    """
    deadline = time.monotonic() + _FILL_WAIT_SECONDS
    while time.monotonic() < deadline:
        detail = sandbox_broker.get_order_detail(client_order_id)
        status = str((detail or {}).get("status") or "").upper()
        if status in ("FILLED", "PARTIAL_FILLED"):
            return True
        if status in ("CANCELLED", "REJECTED", "FAILED", "EXPIRED"):
            return False
        time.sleep(_FILL_POLL_SECONDS)
    return False


def _arm_exits(
    order: dict,
    stop_price: float | None,
    target_price: float | None,
    client_order_id: str | None = None,
) -> None:
    """Rest the exits under a position the agent just opened: a stop where the
    thesis is wrong, a take-profit where it has played out.

    Both come from the analysis, and both are optional — the trader states them
    only when it has a view, and an implausible level was already discarded
    when the signal was recorded. Whichever exists is placed; inventing the
    missing one would be inventing the exit price of a real trade.

    Best-effort on purpose: a failed exit must not undo a filled buy, because
    the shares are owned either way and raising here would leave the ledger
    disagreeing with the account. It is logged loudly instead — a position
    running naked is worth knowing about.
    """
    price = get_current_price(order["ticker"])
    stop_price, target_price = usable_levels(order["ticker"], stop_price, target_price, price)

    if not stop_price and not target_price:
        _record_unguarded(
            order["ticker"], order["quantity"], "the analysis gave no usable stop or target"
        )
        return

    # The shares have to exist before anything can rest against them.
    if client_order_id and not _await_fill(client_order_id):
        _record_unguarded(
            order["ticker"],
            order["quantity"],
            f"the buy had not filled after {_FILL_WAIT_SECONDS}s, so exits could not be placed "
            "against shares that may not exist",
        )
        return
    try:
        legs = sandbox_broker.place_exit_bracket(
            order["ticker"], order["quantity"], stop_price, target_price
        )
    except Exception as exc:
        log.exception("Couldn't arm exits for %s", order["ticker"])
        _record_unguarded(order["ticker"], order["quantity"], f"the broker refused them: {exc}")
        return
    for leg in legs:
        label = "stop-loss" if leg["kind"] == "stop" else "take-profit"
        db.record_agent_trade(
            ticker=order["ticker"],
            side="sell",
            quantity=order["quantity"],
            client_order_id=leg["client_order_id"],
            placed_at=leg["placed_at"],
            reason=f"{label} resting at ${leg['price']:,.2f}",
            signal_id=None,
            is_stop=True,
            limit_price=leg["price"],
            exit_kind="stop" if leg["kind"] == "stop" else "target",
        )
    log.info(
        "Armed %d exit(s) for %s: %s",
        len(legs), order["ticker"], ", ".join(l["kind"] for l in legs),
    )


def settle_pending() -> list[dict]:
    """Ask the broker about every order still awaiting a fill and apply the
    answer. Returns what changed, so a caller can announce it.

    Resting stops are included deliberately. A stop that triggers is a sale
    the app did not initiate, and it is the one fill nobody is waiting for —
    so if this only ran when the agent next decided, the book would show a
    position that had already been sold, sometimes for a whole day.
    """
    settled: list[dict] = []
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
            settled.append({
                "ticker": trade.ticker,
                "side": trade.side,
                "quantity": filled_qty,
                "price": price,
                "was_stop": trade.is_stop,
                "reason": trade.reason,
                "status": "filled",
            })
        elif status in ("CANCELLED", "REJECTED", "FAILED", "EXPIRED"):
            db.settle_agent_trade(trade.client_order_id, status="rejected")
            settled.append({
                "ticker": trade.ticker,
                "side": trade.side,
                "quantity": trade.quantity,
                "price": None,
                "was_stop": trade.is_stop,
                "status": "rejected",
            })
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
    # Skipped passes are recorded too. Four days of "switched off" is part of
    # the story — a journey that showed only the days something happened would
    # credit the agent with patience it never had the chance to show.
    if not quotes.is_sandbox():
        return _skip("Webull is not in sandbox mode — refusing to trade.")
    if not is_enabled():
        return _skip("The trading agent is switched off.")
    # Checked before the model is asked, not after. Orders are placed at market,
    # and the venue refuses those outside the session
    # (CAN_NOT_TRADING_FOR_FIXGW_NOT_READY_MARKET), so deciding first spends a
    # couple of minutes of GPU to produce orders that cannot be placed — and a
    # decision made on a closed market's prices is stale by the next open
    # anyway, which is why the 13:35 batch re-decides rather than replaying it.
    if not watchdog.is_us_market_hours():
        return _skip(
            "The US market is closed, so no order could be placed. "
            "The agent decides automatically each weekday at 13:35 UTC, "
            "five minutes after the open."
        )

    settled = settle_pending()
    if settled:
        log.info("Settled %d pending order(s) before deciding", len(settled))

    signals = _recent_signals()
    book = agent_book.build_book(price_lookup=get_current_price)
    prices = _price_map([s.ticker for s in signals] + [h.ticker for h in book.holdings])
    book = agent_book.build_book(price_lookup=prices.get)

    # What its own past decisions did. Signal decisions are joined in so the
    # history can say "you bought this on a Hold", which is the pattern worth
    # naming.
    decisions = {s.id: s.decision for s in db.get_recent_signals(limit=200) if s.id}
    closed = agent_book.closed_trades(decisions=decisions)
    # Only fetched when research is actually charged for. Without a price the
    # agent has no scarcity to reason about, and a menu it can take from for
    # free would just be a longer watchlist someone else chose.
    menu = _candidate_menu() if research.is_charging() else None
    decision = _decide(
        book, signals, prices, closed=closed,
        regime_line=current_regime_line(), horizon_days=_horizon_days(), menu=menu,
    )

    reasoning, accepted, rejected = decision
    # getattr, because Decision unpacks like the tuple it replaced and a caller
    # may still hand back a plain one — several tests patch _decide that way.
    # Accepting both is the point of keeping __iter__.
    run = AgentRun(reasoning=reasoning, rejected=rejected, book=book,
                   prompt=getattr(decision, "prompt", ""),
                   response=getattr(decision, "response", ""))
    # **The newest signal per ticker, chosen explicitly.** These three used to
    # be dict comprehensions over the signal list, and a dict comprehension
    # keeps the *last* value it sees. The list arrives newest-first, so the
    # oldest signal won every time a ticker had been analysed twice.
    #
    # On 2026-08-28 the agent bought SMCI and rested the exits from the
    # 27th — a stop of 34.16 and a target of 45.21 — when that morning's
    # analysis had said 34.04 and 49.51. The target was $4.30 out on a
    # 260-share position, and nothing reported it, because both numbers are
    # real levels from real signals.
    latest = _newest_signal_per_ticker(signals)
    signal_by_ticker = {t: s.id for t, s in latest.items()}
    # The stop the analysis named, per ticker. Already checked for
    # plausibility when the signal was recorded (see analysis._trade_plan_levels),
    # with an ATR-derived fallback, so a level here is one worth resting on.
    stops = {t: s.stop_loss for t, s in latest.items() if s.stop_loss}
    # The level the analysis expects it to reach. Same provenance as the stop:
    # stated by the trader, discarded if implausible against the traded price.
    targets = {t: s.price_target for t, s in latest.items() if s.price_target}
    for order in accepted:
        if order["side"] == "research":
            _commission_research(order, run)
            continue
        if order["side"] == "untrack":
            _untrack(order, run)
            continue
        if order["side"] == "adjust":
            outcome = adjust_exits(order["ticker"], order.get("stop"), order.get("target"))
            log.info("Adjust %s: %s", order["ticker"], outcome["message"])
            if outcome["ok"]:
                run.adjusted.append(outcome["message"])
            else:
                run.failed.append((order, outcome["message"]))
            continue
        try:
            result = _place(order, prices.get(order["ticker"]), stops, targets)
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
        if order["side"] == "buy":
            if result.get("exits") is not None:
                _record_exits(order["ticker"], result["exits"])
            else:
                _arm_exits(
                    order,
                    stops.get(order["ticker"]),
                    targets.get(order["ticker"]),
                    client_order_id=result["client_order_id"],
                )
        else:
            # The position is being exited, so any resting exit on it would
            # try to sell shares that are no longer held.
            _cancel_resting_exits(order["ticker"])

    # Settle again on the way out, and re-read the book. A market order placed
    # in session hours fills in well under a second, but nothing would notice
    # until the next scheduled pass — so the Discord post and the dashboard
    # would both spend a day reporting cash that has already been spent, beside
    # an order marked "waiting to fill" that filled immediately.
    if run.placed:
        settle_pending()
        run.book = agent_book.build_book(price_lookup=prices.get)
    _record_run(run)
    return run


def _refusals_json(run: "AgentRun") -> str | None:
    """Everything the agent asked for and did not get, with the reason.

    Screened refusals and broker failures are kept apart because they mean
    different things: the first is the agent asking for something impossible,
    the second is the venue saying no to something reasonable. Reading a month
    of runs, those point at different fixes.
    """
    entries = [
        {"ticker": r.ticker, "side": r.side, "quantity": r.quantity,
         "why": r.why, "refused_by": "screening"}
        for r in run.rejected
    ] + [
        {"ticker": o.get("ticker"), "side": o.get("side"), "quantity": o.get("quantity"),
         "why": why, "refused_by": "broker"}
        for o, why in run.failed
    ]
    if not entries:
        return None
    try:
        return json.dumps(entries)[:4000]
    except (TypeError, ValueError):
        log.exception("Could not serialise this run's refusals")
        return None


def _skip(why: str) -> "AgentRun":
    """A pass that never reached the model, recorded rather than dropped."""
    run = AgentRun(skipped=why)
    _record_run(run)
    return run


def _commission_research(order: dict, run: "AgentRun") -> None:
    """Pay for an analysis and put the ticker where the sweep will find it.

    Tracking is how the analysis actually gets run: the morning sweep reads
    the watchlist, so adding the ticker is the commission. The answer arrives
    tomorrow, which is the honest shape — an analyst does not hand over a
    report the instant you ask for one, and pretending otherwise would mean
    the agent could research and act on the same breath with no cost to being
    wrong about what was worth studying.

    **Nothing is charged here.** The charge belongs to the analysis and lands
    when the analysis runs, in propagate_ticker, which already bills every
    ticker the sweep touches — including the ones held rather than
    commissioned. Charging at both ends billed a commissioned ticker twice:
    once for asking and once for the work.

    That leaves the agent able to commission slightly more than its cash on a
    day the sweep has not happened yet. The daily cap bounds that exposure to
    fifteen analyses, so at any sane price it is cents against a four-figure
    budget — a far smaller problem than double-billing, and one the
    affordability screen still catches in the ordinary case.
    """
    ticker = order["ticker"]
    try:
        db.add_to_watchlist(ticker)
    except Exception:
        log.exception("Could not track %s for research", ticker)
        run.failed.append((order, "could not be added to the watchlist"))
        return
    run.researched.append(ticker)
    log.info("Agent commissioned research on %s", ticker)


def _untrack(order: dict, run: "AgentRun") -> None:
    """Stop analysing a ticker every morning.

    The counterpart to ``_commission_research``, and the reason the watchlist
    is no longer a ratchet. Commissioning adds a ticker permanently; without
    this, the only way one ever left was somebody typing ``/untrack``.

    Nothing is refunded. The analyses already run were paid for and produced
    the opinions that led here, so there is nothing to give back — what stops
    is tomorrow's charge, which is the whole point of the decision.

    ``screen`` has already refused this for a ticker the agent still holds.
    """
    ticker = order["ticker"]
    try:
        db.remove_from_watchlist(ticker)
    except Exception:
        log.exception("Could not untrack %s", ticker)
        run.failed.append((order, "could not be removed from the watchlist"))
        return
    run.untracked.append(ticker)
    log.info("Agent stopped watching %s", ticker)


def _orders_json(run: "AgentRun") -> str | None:
    """Every order the pass produced, for the Events page.

    ``agenttrade`` holds the buys and sells, but an untrack, a research and an
    adjust move no shares and leave no row there. Without this the page could
    show a pass that untracked two tickers as having done nothing.
    """
    orders = (
        [{"side": o["side"], "ticker": o["ticker"],
          "quantity": o.get("quantity") or 0,
          "reason": str(o.get("reason") or "")[:300]}
         for o in run.placed]
        + [{"side": "adjust", "ticker": a.split()[0] if a else "", "quantity": 0,
            "reason": a} for a in run.adjusted]
        + [{"side": "research", "ticker": t, "quantity": 0, "reason": ""}
           for t in run.researched]
        + [{"side": "untrack", "ticker": t, "quantity": 0, "reason": ""}
           for t in run.untracked]
    )
    return json.dumps(orders) if orders else None


def _record_run(run: "AgentRun") -> None:
    """Write down what this pass decided, including when it decided nothing.

    The reasoning used to go to Discord and evaporate, which left the record
    with trades and no account of the days between them. A book you can only
    read on the days money moved is a ledger, not a history.

    Never raises. A pass that traded successfully must not be reported as a
    failure because the note about it could not be filed.
    """
    book = run.book
    try:
        db.record_agent_run(
            ran_at=datetime.datetime.now(datetime.timezone.utc),
            reasoning=run.reasoning,
            placed=len(run.placed),
            rejected=len(run.rejected),
            failed=len(run.failed),
            adjusted=len(run.adjusted),
            skipped=run.skipped,
            refusals=_refusals_json(run),
            prompt=run.prompt or None,
            response=run.response or None,
            orders=_orders_json(run),
            equity=book.equity if book else None,
            cash=book.cash if book else None,
            research_spent=book.research_spent if book else None,
        )
    except Exception:
        log.exception("Could not record the agent run")


def format_stop_fill(fill: dict) -> str:
    """A resting exit triggering is the one event here nobody asked for and
    would most want to hear about — a position was sold without anyone
    deciding to sell it that day."""
    hit_target = (fill.get("reason") or "").startswith("take-profit")
    if hit_target:
        return (
            f"🎯 Target reached: sold {fill['quantity']:g} {fill['ticker']} "
            f"at ${fill['price']:,.2f}. The analysis's price target was hit, so the "
            "paper position is closed at a profit."
        )
    return (
        f"🛑 Stop triggered: sold {fill['quantity']:g} {fill['ticker']} "
        f"at ${fill['price']:,.2f}. The thesis level from the analysis was reached, "
        "so the paper position is closed."
    )


@dataclass
class ResetResult:
    cancelled: int = 0
    closed: list[str] = field(default_factory=list)
    cleared: int = 0
    refused: str | None = None


def reset_book(pending_external_flatten: bool = False) -> ResetResult:
    """Return the agent to a flat book and an empty ledger.

    For when the agent itself has changed enough that its record describes a
    system that no longer exists — a new prompt, new rules, exits it did not
    have. Not for a run that went badly: resetting on bad results is how you
    accumulate no evidence at all, and the baselines exist precisely so a bad
    run can be read rather than erased.

    The broker is asked first, and what it says decides the work. An account
    already flat — reset from Webull's own site, say — needs nothing sold, so
    the ledger is simply cleared and the market's hours are irrelevant. Only
    when shares are actually held does this have to cancel and sell, which
    market orders make a market-hours operation.

    The ledger is cleared **only after the account is confirmed empty**.
    Clearing first would leave the ledger claiming nothing while the broker
    still held shares, which is the one disagreement reconciliation cannot
    recover from.
    """
    if not quotes.is_sandbox():
        return ResetResult(refused="Webull is not in sandbox mode.")

    result = ResetResult()
    held = sandbox_broker.get_positions()

    if pending_external_flatten and held:
        # The account is going to be flattened from Webull's own site, so the
        # usual refusal would just block a reset that is genuinely intended.
        # But between now and then the ledger and the account disagree, and an
        # agent trading into that gap would buy positions the site reset then
        # silently wipes — leaving the ledger claiming stock that is gone. So
        # the agent is switched off as part of this, and only turning it back
        # on resumes trading.
        for ticker in sorted(held):
            result.cancelled += _cancel_resting_exits(ticker)
        set_enabled(False)
        result.cleared = db.clear_agent_trades()
        result.refused = (
            f"Ledger cleared and the agent switched OFF. The account still holds {held} "
            "with the exits cancelled — flatten it on Webull's site, then switch the "
            "agent back on."
        )
        log.warning("Ledger cleared ahead of an external flatten; agent disabled")
        return result
    if held is None:
        return ResetResult(refused="Couldn't read the account — nothing was touched.")

    if held:
        # Checked before anything is touched. Market orders are rejected outside
        # the session, so a reset started after the close would cancel the exits,
        # fail to sell, and leave the positions naked overnight — which is how
        # this guard came to exist.
        if not watchdog.is_us_market_hours():
            return ResetResult(
                refused=f"The account still holds {held}, and closing a position needs a "
                "market order. Nothing was touched — reset it on Webull's site, or run "
                "this again once the market opens."
            )
        # Cancel and sell one holding at a time. Cancelling everything up front
        # means a failure on the first sell leaves every other position
        # unprotected too, rather than only the one being closed.
        for ticker, quantity in sorted(held.items()):
            result.cancelled += _cancel_resting_exits(ticker)
            try:
                sandbox_broker.place_market_order(ticker, "SELL", quantity)
                result.closed.append(f"{quantity:g} {ticker}")
            except Exception as exc:
                log.exception("Couldn't close %s during reset", ticker)
                result.refused = f"Couldn't close {ticker}: {exc}"
                return result

        still_held = sandbox_broker.get_positions()
        if still_held is None or still_held:
            result.refused = (
                f"Account still holds {still_held} — the sells may not have filled yet. "
                "Ledger left alone; try again once they have."
            )
            return result

    # Nothing is held, so any exit still resting belongs to a position that no
    # longer exists — an order to sell shares the account does not have.
    for trade in db.get_pending_agent_trades():
        if trade.is_stop and sandbox_broker.cancel_order(trade.client_order_id):
            result.cancelled += 1

    result.cleared = db.clear_agent_trades()
    log.info("Agent book reset: cleared %d ledger row(s)", result.cleared)
    return result


def arm_exits_now(ticker: str) -> dict:
    """Place the missing exits on a position the agent already holds.

    The remediation for a position that ended up unguarded — a bracket the
    broker refused, a buy that filled too slowly, a stop the price had already
    fallen through. All three used to need someone with a Python shell; the
    first time it happened, that someone was reconstructing the right levels by
    hand while the position sat exposed.

    The levels are the same ones a fresh buy would get: the newest signal's,
    screened against the current price, with a volatility-derived stop when the
    stated one cannot be used. Nothing here invents a target — a made-up exit
    price on a real position is worse than none, because it looks decided.

    Refuses rather than duplicates when exits are already resting. Two stops on
    one position sell it twice, and the second sale is a short.

    Returns {"ok": bool, "message": str} — this answers a button, so the reason
    for a refusal has to be readable rather than an exception type.
    """
    from backend.services import ticker_book

    ticker = ticker.upper().strip()
    if not quotes.is_sandbox():
        return {"ok": False, "message": "Webull is not in sandbox mode, so no order can be placed."}

    price = get_current_price(ticker)
    position = ticker_book.agent_position(ticker, price)
    if position is None:
        return {"ok": False, "message": f"The auto trader holds no {ticker}."}
    if position.exits:
        resting = ", ".join(f"{e.kind} at ${e.price:,.2f}" for e in position.exits)
        return {"ok": False, "message": f"{ticker} already has {resting} resting."}

    signal = next(iter(db.get_recent_signals(ticker, limit=1)), None)
    stop, target = usable_levels(
        ticker,
        signal.stop_loss if signal else None,
        signal.price_target if signal else None,
        price,
    )
    if stop is None and price:
        stop = atr_stop(ticker, price)
    if stop is None and target is None:
        return {
            "ok": False,
            "message": (
                f"No usable level for {ticker}: the analysis gives none that the price "
                "has not already passed, and there is too little history to derive one."
            ),
        }

    # The broker takes a standalone order at any hour but refuses a combo —
    # an OCO pair or a bracket — outside 9:30-16:00 ET, because linking legs
    # needs the routing session that only runs then. Rather than telling
    # someone who has already noticed the problem to come back in the morning,
    # remember the request and act on it at the open.
    if not watchdog.is_us_market_hours():
        db.queue_exit_arm(ticker)
        return {
            "ok": True,
            "queued": True,
            "message": (
                f"The market is shut, so {ticker} is queued — the exits go on at the next open. "
                "Nothing is protecting it until then."
            ),
        }

    order = {"ticker": ticker, "side": "buy", "quantity": position.quantity}
    try:
        _arm_exits(order, stop, target)
    except Exception as exc:  # _arm_exits is best-effort, but a broker refusal can still surface
        return {"ok": False, "message": f"The broker refused it: {exc}"}

    placed = ticker_book.agent_position(ticker, price)
    if placed is None or not placed.exits:
        return {
            "ok": False,
            "message": (
                f"Nothing rested on {ticker}. The market is open 9:30–16:00 ET; outside those "
                "hours the broker refuses every order. Check the log for the exact reason."
            ),
        }
    resting = ", ".join(f"{e.kind} at ${e.price:,.2f}" for e in placed.exits)
    return {"ok": True, "message": f"Armed {ticker}: {resting}."}


def process_queued_arms() -> list[dict]:
    """Act on every request queued while the market was shut.

    Called from the intraday pass, which already runs only during market hours,
    so the first tick after the open drains the queue. Returns what happened
    per ticker, so a caller can announce it — a request made the previous
    evening and silently dropped would be worse than not offering the queue.

    Each is re-checked rather than replayed. Hours have passed: the position
    may have been sold, exits may have been placed by a fresh buy, and the
    price has certainly moved, so the levels are computed now rather than
    remembered from when the button was pressed.
    """
    results = []
    for request in db.get_pending_exit_arms():
        try:
            outcome = arm_exits_now(request.ticker)
        except Exception as exc:  # a bad request must not stall the rest of the queue
            log.exception("Queued arming failed for %s", request.ticker)
            outcome = {"ok": False, "message": f"Failed: {exc}"}
        # A request that re-queues itself would loop forever, so a queued
        # answer here counts as failure — the market is open, and if arming
        # still cannot happen the reason is not the hour.
        ok = bool(outcome.get("ok")) and not outcome.get("queued")
        db.complete_exit_arm(request.id, ok, outcome["message"])
        results.append({"ticker": request.ticker, "ok": ok, "message": outcome["message"]})
    return results


def adjust_exits(ticker: str, stop: float | None, target: float | None) -> dict:
    """Move the exits resting under a position to new levels.

    The agent re-reads every holding each day, and until this existed it could
    do nothing with what it learned: the stop and target were fixed when the
    position opened and sat unchanged until it closed. GOOG spent a week with a
    $377.09 take-profit while each morning's analysis put the move's end at
    $345.00 — a level the position would never have reached.

    Letting the model move them is deliberate. Tightening a stop as a trade
    works is what the exits are *for*, and a rule that only ever placed them
    once is not risk management, it is a fossil. What Python keeps is the same
    thing it keeps everywhere else: a level that cannot be executed as stated
    is refused, never silently corrected.

    Replaces rather than cancelling and re-placing. Cancelling first leaves a
    window with nothing under the position, which is the state this app spends
    most of its effort avoiding. A level with nothing resting yet is armed
    instead, so "set my exits to these" works whether or not there are any.
    """
    ticker = ticker.upper().strip()
    if not quotes.is_sandbox():
        return {"ok": False, "message": "Webull is not in sandbox mode, so no order can be placed."}

    price = get_current_price(ticker)
    stop, target = usable_levels(ticker, stop, target, price)
    if stop is None and target is None:
        return {"ok": False, "message": f"No usable level for {ticker} — nothing was changed."}

    resting = {t.exit_kind: t for t in db.get_resting_exits(ticker) if t.exit_kind}
    moved, armed, failed = [], [], []
    for kind, level in (("stop", stop), ("target", target)):
        if level is None:
            continue
        existing = resting.get(kind)
        if existing is None:
            armed.append((kind, level))
            continue
        if existing.limit_price is not None and abs(existing.limit_price - level) < 0.005:
            continue  # already there; a replace would be a round trip for nothing
        try:
            sandbox_broker.replace_exit(existing.client_order_id, kind, level)
        except Exception as exc:
            log.exception("Couldn't move the %s on %s", kind, ticker)
            failed.append(f"{kind} ({exc})")
            continue
        db.move_resting_exit(existing.id, level)
        moved.append((kind, level))

    # Whatever had nothing resting yet is placed now, in one call so a pair
    # still goes out as a pair.
    if armed:
        levels = dict(armed)
        position = next(
            (h for h in agent_book.build_book().holdings if h.ticker == ticker), None
        )
        if position is not None:
            _arm_exits(
                {"ticker": ticker, "side": "buy", "quantity": position.quantity},
                levels.get("stop"),
                levels.get("target"),
            )

    parts = [f"moved {k} to ${v:,.2f}" for k, v in moved]
    parts += [f"placed {k} at ${v:,.2f}" for k, v in armed]
    if failed:
        parts += [f"could not move {f}" for f in failed]
    if not parts:
        return {"ok": True, "message": f"{ticker} exits already at those levels."}
    return {"ok": not failed, "message": f"{ticker}: {', '.join(parts)}."}
