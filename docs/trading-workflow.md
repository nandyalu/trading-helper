# The daily workflow

A practical routine for using the bot.
**The idea: let the automation do the watching. Spend your own attention only where you must actually decide something.**

## Morning (pre-market)

Three posts arrive before the US market opens, in this order:

1. **Webull sync** (12:35 UTC) — This post appears only if something changed. If you bought or sold in the Webull app yesterday, this is where the bot catches up. The bot tracks and analyzes new holdings starting today.
2. **Regime snapshot** (12:45 UTC) — One line of context: `🟢 Market regime: Risk-on · VIX 16.7 (normal) · SPY 8.3% above its 200-day avg · 10Y–3M spread +0.87% (normal)`. Use this line as a *filter*, not as a signal. On a 🔴 day, demand more from Buy signals (see [Finding your edge](finding-your-edge.md)). On a 🟢 day, give a Buy with a strong rationale more benefit of the doubt.
3. **Earnings-triggered analyses** (13:00 UTC) — Any ticker you track that reports within two days gets a fresh look, while you can still act on it. Positions move the most around earnings, so read these rationales in full — do not just skim the decision line.

**Your morning decision:** Did anything arrive that changes what you own or want to own? If yes, size it with the embed's stop-and-share suggestion before the market opens. Or take it as a paper trade (✅) if you are not convinced yet.

## During market hours

The watchdog posts only when something crosses a threshold.
Treat every alert as worth ten seconds of your attention.

- **📊 big move / unusual volume** — Something happened. An ⚡ analysis usually follows automatically. Wait for that analysis before you react to the price alone.
- **🛑 stop breach** — A held position (real or paper) has dropped more than 10% (you can configure this) below your average cost. The bot will *never* sell for you. This alert is your prompt to decide: is your thesis broken, or is the price just noisy? The best time to make this decision is *before* the alert — when you enter the position. That is exactly what the sizing suggestion's stop level is for.
- **🎯 target touch** — A signal's price target was reached while you hold the position. The default action is to take at least partial profit, or to tighten your stop. "It will keep going" is how winners become round trips.

## Evening (after close)

The daily runs post two kinds of message — new analyses from the 11:00 UTC sweep, and grades from the 21:30 UTC pass:

- **Graded signals** — for example: `NVDA Buy from 2026-06-17: PASS ($450.12 → $470.30, +4.5%) · vs SPY +2.1%: PASS (alpha +2.4%) · target $480.00: not hit`. These messages deserve more attention than fresh signals — they are the only messages that tell you whether the bot is any good. If a signal you followed gets a FAIL, use `/ask` to see the original reasoning and find out what it missed.
- **The nightly sweep** — fresh analyses for the whole watchlist. Skim the decision lines. Read the full rationale only where the decision *changed* since yesterday — a Hold-to-Sell flip matters; a fifth straight Hold does not.

React with ✅ on anything you would like to track as if you had traded it.
This costs nothing, and it builds the dataset that tells you whether following the bot actually makes money.

## Weekly (Friday evening or the weekend)

The 🗞️ digest is your review loop:

- **Win rate trend** — Is the last 30 days better or worse than all-time? A trend that gets worse, in a market regime that has changed, is a reason to give new signals less weight.
- **Resolved signals** — Read the failures. Ask `/ask` what the original analysis's thesis was. Over time, you will learn which kinds of calls this model gets wrong. You build that pattern recognition yourself; `/scorecard`'s breakdowns by decision and by ticker are the raw material for it.
- **Paper vs real** — Compare `/paper`'s performance section against `/portfolio`'s vs-SPY line. The paper book follows signals mechanically. If the paper book beats your real book, you are overriding the bot at the wrong times. If your real book beats the paper book, the opposite is true. Either answer is useful to know.

## When to run things manually

- `/analyze` — Before you add to or trim a real position, get a fresh read. Do not act on a signal that is days old.
- `/webullsync` — Run this right after you trade in the Webull app, so your alerts and dashboards reflect reality right away.
- `/scorecard ticker:X` — Before you follow a new signal on ticker X, check how the bot has done *on this specific name*.
- `/digest`, `/regime`, `/portfolio` — Run any of these any time you want the current picture.
