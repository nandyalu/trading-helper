# The daily workflow

A practical routine for working with the bot. The theme: **let the automation
do the watching, and spend your own attention only where a decision is
actually needed.**

## Morning (pre-market)

Three posts arrive before the US open, in order:

1. **Webull sync** (12:35 UTC) — only appears if something changed. If you
   bought or sold in the Webull app yesterday, this is where the bot catches
   up; new holdings are tracked and analyzed from today onward.
2. **Regime snapshot** (12:45 UTC) — one line of context:
   `🟢 Market regime: Risk-on · VIX 16.7 (normal) · SPY 8.3% above its
   200-day avg · 10Y–3M spread +0.87% (normal)`.
   Use it as a *filter*, not a signal: on 🔴 days, demand more from Buy
   signals (see [Finding your edge](finding-your-edge.md)); on 🟢 days a Buy
   with a strong rationale deserves more benefit of the doubt.
3. **Earnings-triggered analyses** (13:00 UTC) — anything you track that
   reports within two days gets a fresh look while you can still act on it.
   Earnings are when positions move most; read these rationales properly
   rather than skimming the decision line.

**Your morning decision:** did anything arrive that changes what you own or
want to own? If yes, size it with the embed's stop/share suggestion before
the open, or take it as a paper trade (✅) if you're not convinced yet.

## During market hours

The watchdog posts only when something crosses a threshold, so treat every
alert as worth ten seconds of attention:

- **📊 big move / unusual volume** — something happened. An ⚡ analysis
  usually follows automatically; wait for it before reacting to the price
  alone.
- **🛑 stop breach** — a held position (real or paper) is more than 10%
  (configurable) below your average cost. The bot will *never* sell for you;
  this is the prompt to decide whether your thesis is broken or the price is
  just noisy. Deciding this *before* the alert — when you enter — is exactly
  what the sizing suggestion's stop level is for.
- **🎯 target touch** — a signal's price target was reached while you hold
  the position. The default action is to take at least partial profit or
  tighten your stop; "it'll keep going" is how winners become round trips.

## Evening (after close)

The 21:30 UTC run posts two kinds of message:

- **Graded signals** — e.g.
  `NVDA Buy from 2026-06-17: PASS ($450.12 → $470.30, +4.5%) · vs SPY +2.1%:
  PASS (alpha +2.4%) · target $480.00: not hit`.
  These deserve more attention than fresh signals: they're the only messages
  that tell you whether the bot is any good. A FAIL on a signal you followed
  is a prompt to `/ask` what the original reasoning was and see what it
  missed.
- **The nightly sweep** — fresh analyses for the whole watchlist. Skim the
  decision lines; read the full rationale only where the decision *changed*
  since yesterday (a Hold→Sell flip matters; the fifth consecutive Hold
  doesn't).

React ✅ on anything you'd like to track as if you'd traded it. It costs
nothing and builds the dataset that tells you whether following the bot
would actually make money.

## Weekly (Friday evening / weekend)

The 🗞️ digest is your review loop:

- **Win rate trend** — is the last 30 days better or worse than all-time?
  A deteriorating trend in a changed market regime is a reason to lighten
  how much weight you give new signals.
- **Resolved signals** — read the failures. `/ask` the original analysis
  what its thesis was; over time you'll learn *which kinds* of calls this
  model gets wrong (that pattern recognition is yours to build, and
  `/scorecard`'s by-decision and by-ticker breakdowns are the raw material).
- **Paper vs real** — compare `/paper`'s performance section against
  `/portfolio`'s vs-SPY line. If the paper book (which follows signals
  mechanically) beats your real book, you're overriding the bot at the wrong
  times — or vice versa. Either answer is valuable.

## When to run things manually

- `/analyze` — before you add to or trim a real position, get a fresh read
  rather than acting on a days-old signal.
- `/webullsync` — right after trading in the Webull app, so alerts and
  dashboards reflect reality immediately.
- `/scorecard ticker:X` — before following a new signal on X: how has the
  bot done *on this specific name*?
- `/digest`, `/regime`, `/portfolio` — any time you want the current picture.
