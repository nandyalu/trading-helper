# Making it a website worth publishing

**Status: Phases 0, 1 and 2 done. Phase 3 next.** Started 2026-09-02.

This file is the working plan for the frontend redesign and the documentation that goes with it. It exists so the work survives a lost session. Update the status marks as phases land.

## What we are building, and for whom

**Intent.** Showcase the experiment.

> **What does an autonomous AI agent\* do with $10,000?**
>
> \* *with guardrails to keep it in bounds. We gave it freedom to choose tickers, analyse them and make trades, and stopped it going out of bounds — no margin, no shorting, no crypto, no options, no real money.*

**Audience, and it is two.**

| | General public | Scientific |
|---|---|---|
| Who | Interested in AI, LLMs and trading | Interested in experiments and LLM behaviour |
| Wants | The story. Is it winning? | Method, limits, reproducibility |
| Reads | The top of the page | All of it, then the raw data |
| Convinced by | Clarity and evident honesty | Stated limitations, variance, sample size |

**The failure mode is averaging them into something that serves neither.** The answer is *progressive depth*: every page opens with the plain-language answer and puts the evidence below it. A general reader stops at the top. A scientific reader keeps going and finds the numbers, the caveats and the prompt verbatim.

## What was wrong with the old frontend

Recorded because the same mistakes are easy to make again.

1. **The shell was an admin panel.** Fixed sidebar, dense equal-weight cards. That layout says "log in and operate this", which is the opposite of the message.
2. **Typography did no work.** One system sans at four sizes. Nothing separated a research write-up from a settings screen.
3. **One flat accent** carried the whole identity.
4. **Everything weighed the same.** The equity curve looked like the alerts table.
5. **A fresh deployment looked broken.** Empty states were unhandled, and empty is exactly what a developer sees on day one.
6. **Nothing to share.** No `og:image`, so a pasted link unfurled as a grey box.

## The name

**The Allowance.** Decided 2026-09-02.

Money given to someone to spend as they choose, inside rules they did not set. That is the setup exactly: $10,000, free choice, hard bounds.

`Trading Helper` was wrong because nothing is being helped — the whole point is that nobody intervenes. `TradingAgents` is the framework this is built on and is already taken.

It also keeps the logo. The mark draws **TA**, which now reads three ways at once: The Allowance, the TradingAgents framework, and the thing being measured.

**Renaming is staged.** The name is in all new copy from today — the site, the docs, The Idea. The repository directory, the package names, the container names and the GitHub remote are left until the site is finished, so a rename does not touch every file while pages are still moving.

Still to rename when the time comes:

- The repo directory and the GitHub remote
- `package.json`, `pyproject.toml`
- `container_name` in the compose files, and the Dockge stacks
- `CLAUDE.md`, `README.md` and the docs
- The database volume name

## Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Visual direction | **Editorial research** | Credible to the scientific reader, approachable to the general one. Not a trading terminal, not a SaaS dashboard. |
| Display face | **Newsreader** | Editorial serif, built for screens. Says "study", not "product". |
| Text and data face | **Inter** | Tabular figures, legible small, huge coverage. |
| Verbatim face | **JetBrains Mono** | For prompts and the agent's answers. |
| Font hosting | **Self-hosted, latin only** | A public site should not tell a third party who is reading it. 8 faces, 680 KB. |
| Default theme | **Light** | Shared links open in daylight. Dark is designed, not derived. |
| Review loop | **Preview route first** | Cheap to redirect before eight pages are built on it. |

## The phases

### Phase 0 — Design system — **done**

- Type scale, colour palette, spacing and radii as a deliberate ratio.
- Chart palette **validated with the dataviz validator**, not eyeballed.
- Dark palette chosen from the same ramps, not flipped.
- **Deliverable: a `/preview` route on real content**, screenshotted for review before anything else changes.

### Phase 1 — The shell — **done**

- Top navigation, content-first layout, generous reading measure.
- Six primary destinations. **About** groups The Idea, Method and Glossary.
- **The footer is a designed component**, carrying credits and the disclaimer, and meant to be read.

### Phase 2 — The landing page — **done**

- Hero with the framing above, and a **working asterisk** that expands into the guardrails: what the agent may do, and what it may not.
- **The disclaimer is prominent.** A standing band under the hero, a line at the top of Book and Research, and the footer. Three placements, because "we put it in the footer" is not a defence.
- **The equity curve is the main object**, red or green against the $10,000 line, so "up or down on where it started" is answered before any number is read.
- **Holdings table**: ticker, shares, average cost, invested, current price, days held, P&L in dollars and percent. Useful, and stopping there.
- **A two-day timeline down the side.** The last trading day with times and one short sentence each, then today or the next trading day with what is scheduled and what has already happened. Past marks filled, future outlined, a now-line between.
  - **Needs a backend addition**: `/api/timeline`, joining the fixed schedule to what actually occurred. Nothing today answers that question.
  - This is what makes the experiment feel *running* rather than *reported*.

### Phase 3 — The other pages

Book, Decisions, Research, Scorecard, Journal, Settings.

- Each opens with a plain-language line saying what the page answers.
- Real hierarchy: the important object on each page looks like it.
- **Designed empty states** — what a fresh deployment shows, and when data will appear.
- Loading skeletons at the shape of the content, and a state for when the API is down.

### Phase 4 — Glossary and tooltips

One `<app-term>` component, one glossary file, one definition per term used everywhere.

First set: refused, broker said no, vs SPY, alpha, maturing, graded, research charge, untrack, unguarded, R-multiple, conviction floor, horizon, regime, bracket, resting exit.

Three rules:

- **Definitions live in the glossary, never inline in a template.** Two explanations of "refused" on two pages reintroduce the ambiguity the tooltip exists to remove.
- **A tooltip explains a word. It never carries a fact you would otherwise miss.** A phone reader who never finds the tap target must lose nothing real.
- **`/glossary` is a page too**, for someone who wants the vocabulary before reading.

### Phase 5 — "The Idea"

By **nandyalu**, linking the GitHub repo. **Claude drafts it; the voice is nandyalu's and the draft is marked as a draft to be corrected.**

- **Why.** A long-standing wish to build some intelligence around trading. Finding TradingAgents, and seeing a way to make it an instrument for learning the market and building a portfolio.
- **How it grew.** An app around that framework, on hardware already on the shelf.
- **The hardware, plainly.** Seven RX 6600s at 8 GiB, 32 GB of host RAM, and what it costs to run.
- **What we tried and what happened.** Gemini Flash-Lite, fast but against a $10/month cap, and the paired comparison never finished. Five models rejected for inventing prices they never fetched. Why `gemma4-e4b-qat-128k` won — including the uncomfortable part, that it is twice as slow as what it replaced and was chosen anyway, because it uses the candidate menu and the faster model does not.
- **What did not work, in as much detail as what did.**

### Phase 6 — Method

The rigorous half, for the scientific reader.

- The design, and what is and is not controlled.
- The guardrails in full.
- How grading works: absolute, vs SPY, target hit — and why vs SPY is the one that counts.
- **Limitations, stated plainly.** Temperature 1 and the 2-of-12 decision agreement measured on 2026-09-02. One analysis is one sample. Small n. The market regime during the run is a confound.
- Hardware, model, and what one analysis costs.

**Publishing the limitations is what separates an experiment from a product demo.**

### Phase 7 — Credits

In the footer on every page, fuller on The Idea. Written as thanks, not a dependency list.

| | For |
|---|---|
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | The multi-agent framework this is built on — the original idea |
| Webull OpenAPI | Market data and the paper-trading account |
| yfinance | Price history behind the bar cache |
| FRED | Macro series |
| Reddit | Social sentiment, via the public RSS |
| Claude Opus 5 | The model that helped build this app |

### Phase 8 — Production readiness

| Area | Work |
|---|---|
| Accessibility | Contrast in both themes, visible focus rings, keyboard navigation, ARIA on charts and toggles, `prefers-reduced-motion` |
| Performance | Self-hosted fonts with `font-display: swap`, no layout shift, lazy charts |
| Sharing | A designed `og:image`, so a pasted link looks like something |
| Resilience | API-down, slow-network and empty states |
| Verification | Every page × both themes × phone, tablet and desktop, screenshotted. Zero console errors. No horizontal overflow. |

### Phase 9 — Documentation

For **developers deploying it themselves**, which is not what `docs/setup.md` is today.

- Prerequisites, honestly stated: a GPU pool or a vendor API key, Webull sandbox credentials, Docker.
- The full environment-variable reference in one table.
- The two-container topology — private plus `PUBLIC_MODE` — and the Cloudflare tunnel.
- **Running it without a GPU pool**, pointing at Gemini instead, with the real costs.
- **The refused / broker-said-no distinction**, in `docs/dashboard.md` under Decisions.
- Troubleshooting, from the failures we actually hit.

## Standing rules for this work

- **All prose goes through the orwell-writing discipline.** Short sentences, one idea each, no jargon a general reader has to decode. Same reason the glossary exists.
- **Markdown is not hard-wrapped.** One sentence or paragraph per line.
- **Behaviour changes go in `JOURNEY.md` before the code**, as always. A tooltip is not a behaviour change; a new API endpoint that the agent's prompt reads would be.
- **No manual controls.** Nothing on this site may nudge the book. That rule survives the redesign.

## Open questions

- The hero figure is read from the API, so it says whatever the deployment says. The copy assumes **$10,000**.
- `_MAX_WATCHLIST` is still 12. The concurrency benchmark suggests about 30. Needs a journal entry before changing.
