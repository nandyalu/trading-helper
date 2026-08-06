# Finding your edge

The bot generates signals.
Whether they make you money depends on how you use them.
This page describes the method the tooling was built around.
None of this is financial advice — it is a discipline for finding out, with evidence, what works for you.

## Step 1: Measure before you trust

Until `/scorecard` shows a meaningful sample, treat every signal as a hypothesis.
Follow these rules:

- **Wait for about 20 or more resolved signals** before you draw conclusions. With five data points, a 60% win rate is noise.
- **The vs-SPY column is the one that matters.** An absolute win rate of 70% in a bull market can be worse than useless — you could have just held SPY and done nothing. The bot beats the market only if the vs-SPY rate is above about 50%, *and* the average alpha is positive.
- **Look for asymmetry by decision type.** Small local models often have a bullish bias. If Buys grade at 65% vs SPY but Sells grade at 30%, the useful conclusion is: follow the Buys and ignore the Sells. Do not conclude "the bot is 50/50".
- **Look for asymmetry by ticker.** The analysts lean on news and sentiment volume. The bot may simply be better at NVDA than at a small cap with thin coverage. Check `/scorecard ticker:X` before you act on ticker X.

## Step 2: Paper trade the strategy, not just the signals

Per-signal grades hide sizing and timing.
The paper book answers the real question: would following this bot have made you money?
It answers this honestly, because it fills at the price when you reacted, not the price the analysis saw.

- React with ✅ on **every** signal you would plausibly follow, not just the exciting ones. A paper book built from a selective subset measures your own selection, not the bot.
- Give it weeks. The `/paper` performance section — the equity sparkline, the max drawdown, and the open-lots alpha against SPY — is the verdict. The drawdown number tells you whether you could have *stomached* the strategy, and that matters as much as the return.
- Only move from signal-following to real dollars after the paper book has survived a drawdown and still shows alpha. Even then, use the sizes `/risk` suggests, not sizes based on your own conviction.

## Step 3: Size positions like every trade can fail

Set `/risk equity:<your account> risk_pct:1` once, and take the embed's suggestion seriously.

- The stop is `entry − 2×ATR(14)`. This is wide enough that normal daily noise does not stop you out, and tight enough that a broken thesis costs you the planned amount and no more.
- The bot derives the share count *from* that stop: it risks 1% of your equity between entry and stop. This is what makes a strategy with a 45% win rate survivable — ten losers in a row cost about 10% of the account, not the whole account.
- The 🛑 watchdog alert enforces this plan. When it fires, you already made the decision, back at entry — you are just executing it now. Overriding a stop "because it will come back" is the single most expensive habit; the tooling cannot fix this habit for you.
- The concentration warning in `/portfolio` (any name at 30% of the book or more) applies the same idea at the portfolio level.

## Step 4: Let the regime scale your aggression

The 🟢/🟡/🔴 line is a blunt instrument, but blunt instruments are hard to fool.

- **🟢 Risk-on** — Normal operation. Follow qualified Buy signals at the suggested size.
- **🟡 Mixed** — Halve `risk_pct`. Demand a vs-SPY-positive scorecard on the specific ticker. Prefer adding to winners over opening new names.
- **🔴 Risk-off** — New Buys need an exceptional rationale. This is when Sell and trim signals on your holdings deserve *more* weight, not less. The classifier encodes a historical pattern — elevated VIX, price under the 200-day average, an inverted yield curve — and that pattern is exactly the environment where buying dips stops working.

## Step 5: Interrogate before you act, and review after you lose

- Before you follow a signal, ask `/ask` the questions a skeptic would ask: "What is the bear case?", "What would invalidate this thesis?", "How much of this is sentiment, and how much is fundamentals?" A rationale that survives three hostile questions is worth more than a confident decision line.
- After a graded FAIL on something you followed, ask `/ask` what the original reasoning was, and find *which analyst* got it wrong — news, or technicals? Patterns emerge fast. For example, you might notice "sentiment-driven Buys on meme-adjacent names keep failing." Each pattern you find becomes a personal filter that the scorecard alone cannot give you.

## The loop, compressed

> Sync holdings → let the bot analyze → paper-follow everything plausible → measure for weeks → follow only the signal types with a proven vs-SPY edge → size every real trade off the ATR stop, at 1% risk or less → let stops and targets fire mechanically → review failures every week → repeat.

The bot's job is to make each step of that loop cheap.
Your job is to not skip the measuring steps.
That discipline, not the AI, is the real edge.
