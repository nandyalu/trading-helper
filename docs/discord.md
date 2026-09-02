# What Discord posts

**Discord reports. It does not take orders.**

There are no slash commands. The app had twenty-three of them and every one was removed on 2026-09-01. A control that lets a person nudge the book puts a second decision-maker in the record, and afterwards nothing can tell which one produced a result.

The channel carries what the agent did. It is short by design, so an alert in it is worth reading.

## The scheduled posts

| When (UTC, weekdays) | Post |
|---|---|
| 12:45 | 🟢/🟡/🔴 the market regime line — VIX, SPY against its 200-day average, the yield curve |
| 13:00 | 📅 "X reports earnings soon", for a tracked ticker reporting within two days |
| 13:35 | **The decision pass.** What the agent bought, sold, adjusted, commissioned or untracked, and why. Silent on a day it did nothing |
| 21:30 | Graded signals — "PASS/FAIL, vs SPY, target hit" |
| Fri 23:00 | 🗞️ the weekly digest |

## The alerts

The watchdog runs every fifteen minutes during market hours and posts only when something crosses a threshold.

| Alert | What it means |
|---|---|
| 📊 big move | A tracked ticker moved more than the configured percentage today. An analysis usually follows |
| 📊 unusual volume | Volume is above the configured multiple of the 20-day average |
| 🛑 stop breach | A holding is below the agent's average cost by more than the configured percentage |
| 🎯 target touch | A holding reached the price target from its signal |
| 🛑 / 🎯 a fill | A resting stop or take-profit executed. These arrive within a second of the fill |
| ⚠️ unguarded position | The agent holds shares with nothing resting at the broker to close them |
| 📝 the agent asked for something | It said what would help it decide better — a tool it lacks, a number it cannot see |

Each alert posts at most once a day. A target alert posts once ever, per signal.

## What Discord does not post

**The analyses themselves.** Each one runs to thousands of words and several arrive a morning. They are read on the Signals page, where they can be scrolled, compared, and opened beside the decision that used them.

## When the agent asks for something

The agent can end a decision pass with a note. It is a message to whoever maintains it: a tool it does not have, data it cannot see, a rule it finds contradictory.

**Nothing acts on it.** It is the agent talking, not the agent trading, so it puts no second decision-maker in the record. If we build what it asks for, that is a change like any other and goes in the journal first.

A note never replaces a decision. The prompt says so outright — otherwise "I need better data" becomes a way to avoid answering, and a pass that owed a decision returns a request instead.

It appears high in the Discord post and in its own block on the Decisions page, apart from the orders.

## The unguarded-position alert

This is the one alert that asks for a person.

A buy goes out as a bracket — the entry with a stop and a take-profit attached — so the shares are normally never held with nothing under them. Webull refuses a bracket while the cash is unsettled, which happens routinely when the agent sells to fund a buy. The app falls back to a plain order and then arms the exits separately, and that second step can fail.

When it does, the position is live and unprotected. The alert says so, and the ticker page has a button that rests the missing exits. **That button decides nothing** — it places the stop and target the agent already chose, under shares it already owns, which is the one action that can only reduce exposure.

## Setting the channel

`DISCORD_CHANNEL_ID` in the environment. There is no `/setchannel` command any more: a person who can move the channel by typing can move it without leaving a record of having done so.
