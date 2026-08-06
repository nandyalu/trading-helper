# Finding your edge

The bot generates signals; whether they make you money depends on how you
use them. This page is the method the tooling was built around. None of it
is financial advice — it's a discipline for finding out, with evidence,
what works for you.

## Step 1: Measure before you trust

Until `/scorecard` shows a meaningful sample, treat every signal as a
hypothesis. Concretely:

- **Wait for ~20+ resolved signals** before drawing conclusions. With five
  data points, a 60% win rate is noise.
- **The vs-SPY column is the one that matters.** An absolute win rate of 70%
  in a bull market can be worse than useless — you could have held SPY and
  slept. The bot beats the market only if the vs-SPY rate is above ~50% *and*
  average alpha is positive.
- **Look for asymmetry by decision type.** Small local models often have a
  bullish bias. If Buys grade 65% vs SPY but Sells grade 30%, the actionable
  conclusion is: follow the Buys, ignore the Sells — not "the bot is 50/50".
- **Look for asymmetry by ticker.** The analysts lean on news and sentiment
  volume; the bot may simply be better at NVDA than at a thinly-covered
  small cap. `/scorecard ticker:X` before acting on X.

## Step 2: Paper trade the strategy, not just the signals

Per-signal grades hide sizing and timing. The paper book answers the real
question — *would following this bot have made money?* — because it fills at
the price when you reacted, not the price the analysis saw.

- React ✅ on **every** signal you'd plausibly follow, not just the exciting
  ones. A selectively-built paper book measures your selection, not the bot.
- Give it weeks. The `/paper` performance section (equity sparkline, max
  drawdown, open-lots alpha vs SPY) is the verdict; the drawdown number
  tells you whether you could have *stomached* the strategy, which matters
  as much as the return.
- Only after the paper book has survived a drawdown and still shows alpha
  should signal-following graduate to real dollars — and then at the sizes
  `/risk` suggests, not at conviction sizes.

## Step 3: Size positions like every trade can fail

Set `/risk equity:<your account> risk_pct:1` once, and take the embed's
suggestion seriously:

- The stop is `entry − 2×ATR(14)` — wide enough that normal daily noise
  doesn't stop you out, tight enough that a broken thesis costs you the
  planned amount and no more.
- The share count is derived *from* that stop: risking 1% of equity between
  entry and stop. This is what makes a 45%-win-rate strategy survivable —
  ten losers in a row costs ~10% of the account, not the account.
- The 🛑 watchdog alert is the enforcement mechanism. When it fires, the
  decision was already made at entry; you're just executing it. Overriding
  a stop "because it'll come back" is the single most expensive habit the
  tooling can't fix for you.
- The concentration warning in `/portfolio` (any name ≥30% of the book) is
  the portfolio-level version of the same idea.

## Step 4: Let the regime scale your aggression

The 🟢/🟡/🔴 line is a blunt instrument, but blunt instruments are hard to
fool:

- **🟢 Risk-on** — normal operation: follow qualified Buy signals at
  suggested size.
- **🟡 Mixed** — halve `risk_pct`, demand a vs-SPY-positive scorecard on the
  specific ticker, prefer adding to winners over opening new names.
- **🔴 Risk-off** — new Buys need an exceptional rationale; this is when
  Sell/trim signals on your holdings deserve *more* weight, not less. The
  historical pattern the classifier encodes (elevated VIX, price under the
  200-day, inverted curve) is exactly the environment where buying dips
  stops working.

## Step 5: Interrogate before you act, post-mortem after you lose

- Before following a signal, `/ask` the questions a skeptic would:
  "what's the bear case?", "what would invalidate this thesis?",
  "how much of this is sentiment vs fundamentals?" A rationale that survives
  three hostile questions is worth more than a confident decision line.
- After a graded FAIL on something you followed, `/ask` what the original
  reasoning was and identify *which analyst* was wrong (news? technicals?).
  Patterns emerge fast — e.g. "sentiment-driven Buys on meme-adjacent names
  keep failing" — and each one becomes a personal filter the scorecard
  can't give you.

## The loop, compressed

> Sync holdings → let the bot analyze → paper-follow everything plausible →
> measure for weeks → follow only the signal types with proven vs-SPY edge →
> size every real trade off the ATR stop at ≤1% risk → let stops and targets
> fire mechanically → review failures weekly → repeat.

The bot's job is to make each step of that loop cheap. Yours is to not skip
the measuring steps — that discipline, not the AI, is the actual edge.
