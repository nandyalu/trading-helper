"""What time it is, in the only frame the agent's decisions live in.

**The agent had no clock.** Nothing in its prompt said what time it was, and
it was reasoning about a trading day with no idea how much of one was left.
That was survivable while it decided once at the open and went quiet. It is
not survivable once it chooses its own next wakeup, which is a question about
the time.

Everything here is Eastern, because the session is. Showing UTC would make the
agent convert before it could reason, and a model doing arithmetic it does not
need to do is a model with one more thing to get wrong.
"""
import datetime

from backend.services.watchdog import US_MARKET_TZ, _MARKET_CLOSE, _MARKET_OPEN

# How long a pass may ask to sleep. The floor is not a limit on judgment: below
# it the book has not moved enough to be worth a fresh opinion, and the agent
# would be reading the same numbers again. The ceiling exists so "later" can
# never mean "after the close" by accident — the end-of-day pass covers that.
MIN_WAKEUP = datetime.timedelta(minutes=5)
MAX_WAKEUP = datetime.timedelta(hours=6)

# The last pass of the day, five minutes before the close. It runs whatever the
# agent asked for, so no position goes into the night unreviewed.
FINAL_PASS = datetime.time(15, 55)


def now_et(now: datetime.datetime | None = None) -> datetime.datetime:
    return (now or datetime.datetime.now(US_MARKET_TZ)).astimezone(US_MARKET_TZ)


def close_today(now: datetime.datetime | None = None) -> datetime.datetime:
    return now_et(now).replace(
        hour=_MARKET_CLOSE.hour, minute=_MARKET_CLOSE.minute, second=0, microsecond=0
    )


def minutes_to_close(now: datetime.datetime | None = None) -> int:
    """Negative once the session is over, which reads correctly as "past it"."""
    return int((close_today(now) - now_et(now)).total_seconds() // 60)


def next_open(now: datetime.datetime | None = None) -> datetime.datetime:
    """The next weekday open. Holidays are not modeled, matching
    ``is_us_market_hours`` — a pass on a closed day finds nothing and costs one
    prompt."""
    here = now_et(now)
    candidate = here.replace(
        hour=_MARKET_OPEN.hour, minute=_MARKET_OPEN.minute, second=0, microsecond=0
    )
    if candidate <= here:
        candidate += datetime.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += datetime.timedelta(days=1)
    return candidate


def describe(now: datetime.datetime | None = None) -> str:
    """One line, first in the prompt."""
    here = now_et(now)
    stamp = here.strftime("%A %-d %B, %-I:%M %p").replace(" 0", " ")
    left = minutes_to_close(now)
    if here.weekday() >= 5:
        return f"It is {stamp} Eastern. The market is closed for the weekend."
    if left < 0:
        return f"It is {stamp} Eastern. The market has closed for the day."
    if left == 0:
        return f"It is {stamp} Eastern. The market closes now."
    hours, minutes = divmod(left, 60)
    span = f"{hours}h {minutes}m" if hours else f"{minutes} minutes"
    if not (_MARKET_OPEN <= here.time() <= _MARKET_CLOSE):
        return f"It is {stamp} Eastern. The market has not opened yet; it opens at 9:30 AM."
    return f"It is {stamp} Eastern. The market closes in {span}, at 4:00 PM."


def clamp_wakeup(
    requested: datetime.datetime | None, now: datetime.datetime | None = None
) -> datetime.datetime | None:
    """Pull a requested wakeup into a time the market is actually open.

    Returns None when the agent asked for nothing, which the scheduler treats
    differently from a bad request: no answer is not a decision, so it falls
    back rather than pretending the agent chose the fallback.

    A time past today's close becomes the next open. **Not the end-of-day
    pass** — that one runs regardless, and folding a request into it would
    silently turn "look at this tomorrow" into "look at this at 3:55".
    """
    if requested is None:
        return None
    here = now_et(now)
    wanted = requested.astimezone(US_MARKET_TZ)

    earliest = here + MIN_WAKEUP
    if wanted < earliest:
        wanted = earliest
    latest = here + MAX_WAKEUP
    if wanted > latest:
        wanted = latest

    close = close_today(now)
    if wanted > close or here.weekday() >= 5 or wanted.time() < _MARKET_OPEN:
        return next_open(now)
    return wanted
