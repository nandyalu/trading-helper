# trading-helper — Claude Code context

Discord bot + FastAPI/Angular dashboard (`backend/`) delegating analysis to a
vendored multi-agent framework (`TradingAgents/`, registered as a git
submodule of this repo — see "Vendored TradingAgents repo" below for the
remote/branch details). See [README.md](README.md) and
[docs/overview.md](docs/overview.md) for architecture/commands — this file
only covers what those don't.

## Markdown conventions

Don't hard-wrap prose — write each sentence (or paragraph) on one line, no
matter how long. Zensical (the `docs/` site generator) sometimes mis-renders
a sentence that's been split across multiple source lines. Applies to every
`.md` file in the repo, not just `docs/`.

## Deployment topology (important, non-obvious)

Two copies of the compose config exist and are **not synced automatically**:

- `dockge/trading-bot.compose.yaml` — local-only working template
  (`dockge/` is gitignored, not tracked in this repo). Edit this one.
- `/opt/stacks/trading-bot/compose.yaml` + `.env` — the actually-deployed
  copy, managed via the Dockge UI. **Root-owned**, outside this repo, and
  already drifted from the template (Discord/Webull secrets are pasted in
  directly there instead of using `${VAR}` substitution). Applying a repo
  edit to the deployed stack means manually re-applying the diff in the
  Dockge UI's compose editor — never wholesale-replace its `environment:`
  block or you'll clobber the hardcoded secrets.

To inspect the live container: `docker logs trading-bot`, `docker exec
trading-bot env`. Don't sudo-edit `/opt/stacks/...` directly — hand the user
the exact diff/snippet to paste into the Dockge UI instead (their stated
preference).

## Ollama pool topology (deployed ≠ the repo template)

`dockge/ollama-pool.compose.yaml` describes **two** backends (`ollama-pool`,
`ollama-pool-b`) behind an nginx round-robin named `ollama-lb`. That is stale.
What actually runs (verified 2026-08-06):

- **Seven** backends: `ollama-pool-a` … `ollama-pool-g`, one AMD card each (three added 2026-08-26).
  The cards are **RX 6600 (gfx1032, 8 GiB)**, not gfx1030 as an earlier note
  here claimed. They report as gfx1030 only because every pool container sets
  `HSA_OVERRIDE_GFX_VERSION=10.3.0` — ROCm's support for gfx1032 is unofficial
  and the override is what makes them work. Anyone adding cards who trusts the
  old note would omit it and spend a day on it.

  Each container is pinned to one card at the device level — `/dev/dri/card0`
  plus `renderD128` for `-a`, `card1`/`renderD129` for `-b`, and so on — which
  is why `HIP_VISIBLE_DEVICES=0` is correct in every one: it means "the only
  card I can see", not "card zero". `-e`…`-g` follow the same pattern on
  `card4`…`card6` with `renderD132`…`renderD134`.

  **Every pool container bind-mounts the same host directory** at
  `/root/.ollama/models` (`/opt/stacks/ollama-gpus/ollama/models`), so a model
  pulled or built through any one of them is immediately visible to all. There
  is no per-backend model state to keep in sync, and adding a card needs no
  model work at all.
- `ollama-proxy` (image `ollama-proxy:local`) replaced nginx. It is a small
  FastAPI app: least-active-connections routing, `CONCURRENCY_PER_BACKEND=1`,
  `WAIT_TIMEOUT=600` (queues rather than 503s), and a `/healthz` endpoint
  reporting per-backend health and active count. Still on host port 11435.

**One analysis occupies exactly one GPU.** TradingAgents' graph is internally
sequential — analysts run one after another, then the debate, then the trader —
so a single `propagate()` never has more than one LLM request in flight. Extra
GPUs are only used by running *several analyses at once*.

That is about concurrency, not stickiness. **An earlier note here said the
proxy scatters one analysis's ~20 calls across whichever backends are idle.
That is no longer true**: the proxy polls each backend's `/api/ps` and prefers
a free backend that already holds the requested model warm, so a *sequential*
run stays on one card. Concurrent runs still spread, which is the intent.

Benchmarking still has to bypass the proxy, for a different reason: you cannot
tell which card served a run. The pool containers' docker-bridge IPs are
reachable from the host
(`docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
ollama-pool-a`), so pointing `OLLAMA_BASE_URL` at `http://<ip>:11434/v1` pins a
run to one card. **And measure one model at a time.** Seven cards are not seven
independent measurements — gemma4's E-series keeps its per-layer embeddings in
host RAM, so every card competes for the same CPU and memory bandwidth. The
same model at the same context measured 43.5, 28.0 and **69.6** tok/s depending
only on how busy the rest of the pool was (2026-08-26).

That makes `TRADINGAGENTS_MAX_CONCURRENT_ANALYSES` the knob that decides GPU
utilization. With one deployment it should equal the backend count; anything
above just queues in the proxy.

**With two deployments sharing the pool, the sum across them is what must not
exceed the backend count**, because both sweep at 11:00 UTC and contend. Seven
backends split 5 (live) / 2 (analyst): the live sweep has a fixed nine tickers,
the analyst usually fewer. Overshooting the sum is not fatal — the proxy queues
rather than refusing — but `WAIT_TIMEOUT=600` is ten minutes against an
eight-minute analysis, so a third wave of queued work starts timing out.

Every multi-ticker caller must go through `analysis.run_analyses()`, which
dispatches with `asyncio.gather` and lets the shared semaphore do the bounding.
A `for ticker in …: await run_analysis_and_notify(ticker)` loop looks correct
and silently pins the whole sweep to one GPU — that bug shipped in the daily
sweep, the watchdog triggers, and the earnings check.

To check which backends served a run:
`docker logs --since 24h ollama-pool-a | grep "starting runner"` (an idle
backend has no recent entries), or `curl localhost:11435/healthz`.

## Custom context builds (`ollama/`)

`ollama/*.Modelfile` plus `ollama/build.sh`. **An earlier note here said a
model has to be installed on every backend or the proxy sends some analyses to
one that lacks it. That was wrong**: the pool shares one models directory, so
building once reaches all of them. The script builds on the first backend and
then checks the rest can see it, which is cheap and catches the day somebody
gives a container its own volume. See `ollama/README.md` for the numbers.

The non-obvious part, measured 2026-08-11 on the 8 GiB cards: **the
compute graph is what limits context, not the KV cache.** The cache is already
`q4_0` (flash attention is on) and costs 2.6 GiB at 96k, while the compute
graph at the default `num_batch 512` wants 5.1 GiB and pushes 40% of a
llama-3.2-3B's layers onto the CPU. Dropping `num_batch` to 64 fits the full
128k in 6.6 GiB, entirely on the GPU, for 16% slower prefill (411 vs 490
tok/s). So a new build needs `PARAMETER num_batch`, not just `num_ctx`, and
`ollama ps` must read `100% GPU` — any CPU split costs far more than the batch
size ever will.

Gemma is the exception that made this confusing: `gemma4-e2b-96k` runs at 96k
with the default batch because sliding-window attention keeps its compute graph
small. Don't reason from it to a Llama of the same size.

## LLM provider switching

`TradingAgents/tradingagents/llm_clients/` is a full multi-provider
abstraction (ollama, google, openai, anthropic, azure, bedrock, etc.) —
switching providers is a config change, not a code change. Controlled via
three vars threaded through `dockge/trading-bot.compose.yaml`'s
`environment:` block into the stack `.env`:

- `LLM_PROVIDER` (defaults to `ollama`)
- `LLM_MODEL` (defaults to `qwen3:latest`) — used for both
  `TRADINGAGENTS_DEEP_THINK_LLM` and `TRADINGAGENTS_QUICK_THINK_LLM` (they
  share one value; splitting them needs a small code change in
  `TradingAgents/tradingagents/graph/trading_graph.py`)
- `GOOGLE_API_KEY` (passthrough, only relevant when `LLM_PROVIDER=google`)

**The model is also a runtime setting.** `analysis.get_model()/set_model()`
store it in `BotSetting` under `llm_model` and `_build_graph()` applies it to
both think stages, so `/model` or the settings page switches models without a
redeploy. The env var above is only the default for an unset setting.
`analysis.model_choices()` lists what the endpoint actually serves, via the
OpenAI-compatible `/v1/models` route (ollama serves it too), and an
unreachable endpoint degrades to a free-text field rather than blocking a
save. Every `Signal` records `model`, and the scorecard's `by_model`
breakdown is the point of the whole mechanism — switching models teaches you
nothing if the win rates blend.

**A larger gemma4 now fits, and the analyst should use it (measured
2026-08-26/27; recommended, not yet switched — the analyst still runs
`gemma4-e2b-96k`).** `gemma4:e4b-it-qat` (8.0B raw, 4B effective) runs **100%
on the GPU at the full 131,072-token context**, using 3.7 GiB of the 8 GiB
card. Built here as `gemma4-e4b-qat-128k`. `gemma4:12b` does not fit at any context
— two to five layers always land on the CPU, and the QAT build does not rescue
it — and `gemma4:26b` (MoE, 4B active) is far worse. Full numbers in
[ollama/README.md](ollama/README.md).

**Take the QAT tag, not the default one.** `gemma4:e4b-it-qat` beats plain
`gemma4:e4b` where it has been measured repeatably: 1,122 tok/s prefill against
861 (30% faster, and prefill is what sets run time), 6.1 GB on disk against
9.6, slightly less VRAM, same 43/43 placement, same menu behaviour (4 of 4
each). Quantization-aware training puts the 4-bit rounding inside the training
loop rather than applying it to a finished model, so it should also be the more
accurate of the two. `gemma4:e4b-it-q4_K_M` is not a third option — same
manifest id as `gemma4:e4b`.

**Measure prefill on a long, cache-busted prompt.** A 30-token prompt measures
per-request overhead, not prefill, and ranked QAT *below* plain e4b — the exact
opposite of the truth. Repeating an identical prompt is as bad: Ollama's prompt
cache returns the second one in 0.03s, which reads as 219,000 tok/s. Use
several thousand tokens with a unique prefix per run.

The reason to switch off e2b is not speed; e4b is about **twice as slow**
(13m12s alone, 17m26s when two run together, against e2b's 7m15s). It is that
e4b uses the candidate menu and e2b does not. On the identical deployed prompt,
both e4b builds chose research in 4 runs of 4, picking 4-5 names of 15 with a
stated reason each; e2b managed 2 of 4, and had answered "no research" three
real mornings running. It also passes the tool-calling test that disqualified
four earlier models: 18-26 calls and **99-174k prompt tokens against the
baseline's 103k**, which is the right direction — every model that failed here
was faster because it never fetched the data. The prices are real too: AAPL's
actual $313.45 close appears verbatim in three of four runs.

**One structured-output failure per run is normal for the e4b family** — both
builds logged one, at the Sentiment Analyst or Trader stage, and both recovered
by retrying as free text. Do not read that as a QAT defect; plain `gemma4:e4b`
does it too. It is a different thing from the four-per-run failures that
disqualified `llama3.2:3b` and `phi4-mini`. Treat a count above one, or a
failure that does not recover, as a regression.

**The same ticker on the same day gave Underweight, then Overweight.** Plain
e4b gave Underweight, then Hold. That is temperature 1 — Gemma's recommended
setting, which `gemma4-e2b-96k` has been running at in production all along —
so it is not new with e4b and not a reason to tune sampling down. It does mean
a single analysis is one sample, and the Scorecard's `by_model` breakdown is
the only honest way to compare two models.

**Timing is the real cost, and it needs acting on before the first sweep, not
after one overruns.** At `TRADINGAGENTS_MAX_CONCURRENT_ANALYSES=2` the analyst
needs three waves for six tickers, which at the paired 17.4 minutes is **52
minutes against the hour before the open** — and the live sweep contends for
the same cards at 11:00 UTC, with `WAIT_TIMEOUT=600` being ten minutes against
a seventeen-minute analysis. Split the seven backends 4/3 rather than 5/2
before switching. After that, lower the research cap or move the sweep earlier;
reverting to e2b gives up the feature e4b was chosen for.

**Sampling stays at Gemma's published values** — temperature 1 / top_k 64 /
top_p 0.95 (<https://ollama.com/library/gemma4>). `gemma4-e2b-96k` briefly ran
at 0.15/20/0.9 on 2026-08-26 to make the agent's research choice consistent;
that treated a symptom of the 2B model's capability as a sampling problem and
is reverted. Separately and still true: the app talks to Ollama over
`/v1/chat/completions`, which **silently ignores `temperature` in the request
body**, so `TRADINGAGENTS_TEMPERATURE` does nothing and a Modelfile is the only
channel that reaches the model.

**Current model for the live bot (2026-08-11):** `gemma4-e2b-96k`, a custom Modelfile build of
`gemma4:e2b` with the context raised to 96k. A full analysis takes about 7
minutes, against roughly 15 for `qwen3:latest`. That is 23 LLM calls spending
roughly 142k tokens, about 86% of them prompt tokens (one AAPL run measured
2026-08-11). An earlier "2-3 minutes" figure here was wrong: 7 matches both
that run and days of observed sweeps.

**Four small models have now been tested against this pipeline and all four
failed the same way** (kotakneo and alma-trader 2026-08-11; `llama3.2:3b` and
`phi4-mini` 2026-08-12). They cannot drive TradingAgents' tool-calling loop:
either they print the tool call as text and invent its output, or they never
retrieve the data and answer anyway. Measured on one AAPL run each, against
gemma4-e2b-96k's 7m15s / 21 calls / 123k tokens / **0** structured-output
failures:

| Model | Time | Tokens | Structured-output failures | What the market report contained |
|---|---|---|---|---|
| `llama3.2:3b` @128k | 3m23s | 52k | 4 | "no available market data for AAPL" — then issued a Buy anyway |
| `phi4-mini` @96k | 4m10s | 49k | 4 | the raw tool call as text, plus fabricated 2023 OHLCV around $130 for a stock at $308 |

They are faster because they do **half the work** — 42-45k prompt tokens against
gemma4's 103k — having never fetched the data there was to reason over. Treat a
sharp drop in prompt tokens as a symptom, not a win. Raising context to 128k
does not help, because it was never a context problem; don't retest these
without a fix for tool calling.

This supersedes an earlier "known-bad model" note about `gemma4:e2b`. Stock
`gemma4:e2b` did hit a `GraphRecursionError` on ZBH — its reasoning loop never
terminated — but that was a context-length failure: tool-call history was being
truncated out from under the loop. At 96k the failure does not occur. Don't
revert to stock `gemma4:e2b` at the default context; `qwen3:latest` stays the
known-good slow fallback.

Analysis speed is what makes the 1-2 week trade horizon practical — signals
have to be produced faster than they expire — so treat a regression here as a
correctness problem, not a performance one.

**Gemini capacity note (2026-07-30):** `gemini-3.5-flash` returned 100%
persistent `503 UNAVAILABLE` ("high demand") over ~12h straight — looked
like a tier/capacity issue with that specific just-GA'd model, not a
transient blip. `gemini-3.1-flash-lite` worked reliably (16/16 calls
succeeded), ran a full analysis in <1 min vs Ollama's ~15 min, at roughly
$0.02–0.08/analysis. If revisiting Gemini, start with `flash-lite`, not
`3.5-flash`.

### What Gemini actually bills (measured 2026-08-22 and 2026-08-25)

**`gemini-2.5-flash-lite` is retired.** It still appears in the models list,
and calling it returns `404 NOT_FOUND`: "no longer available to new users.
Please update your code to use `models/gemini-3.5-flash-lite`". Both
`gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` work on a current key, so
3.1 remains the fallback the capacity note above points at.

Speed is not in doubt and is the reason to care: a Flash-Lite analysis takes
**1.2-1.6 minutes** against gemma4-e2b-96k's **7-10**, on the same tickers the
same morning. A nine-ticker sweep is ~11 minutes of wall clock against ~85 of
GPU.

The cost is less settled.

**Always price input and output separately. Never use a blended rate.**

List is $0.30 per 1M input and $2.50 per 1M output — an 8x gap — so a blended
figure is a function of the completion share, not a property of the model:

| Completion share | Implied blended rate |
|---|---|
| 8.5% (a Flash-Lite sweep) | $0.487 / 1M |
| 16.0% (gemma4's history) | $0.652 / 1M |
| 25% | $0.850 / 1M |

This is not academic. An earlier revision of this file derived $0.399/1M from a
single Flash-Lite run and applied it to gemma4's 11.49M-token history, which
runs at 16% completion. That produced **$4.59** where the correct split-rate
answer is **$7.49** — 39% low, and it replaced a figure that had been right.
Blending was the entire error.

**Two measurements, and they disagree.** Priced at list, with rates split:

| | 22 Aug — 1 analysis | 25 Aug — 9 analyses |
|---|---|---|
| Prompt / completion | 90,713 / 9,629 | 911,876 / 84,189 |
| Completion share | 9.6% | 8.5% |
| List cost | $0.051 | $0.484 |
| Billed | $0.04 | $0.50 |
| **Billed vs list** | **78%** | **103%** |

The first reading looked like an implicit-caching discount and was written up
here as one. The second says otherwise, and three explanations fit without
being distinguishable from the dashboard: a single $0.04 line item rounds
coarsely and may simply have displayed $0.0513 as $0.04; caching may behave
differently for one analysis than for nine dispatched together; or the $0.50
may carry trailing usage that had not settled on the 22nd.

**So estimate at list.** It sat within 3% of the larger sample and does not
rest on caching behaviour nobody here has verified.

Projections for the current 9-ticker watchlist, at the 25 Aug measurement:
**$0.056/analysis, $0.50/sweep, $2.50/week, $10.58/month.**

Note the month figure **exceeds the $10/month billing cap** on the account. The
week-long comparison is only $2.50 and fits easily, but running this
indefinitely would trip the cap, and adding tickers or ever pointing the *main*
model at Gemini would trip it sooner. Intraday triggers cost nothing — only the
morning sweep chains a comparison run.

**Against self-hosting.** Running the whole history to date on Flash-Lite —
9,656,261 prompt + 1,837,356 completion — would have cost **$7.49** at list,
against **$0.26** of marginal GPU electricity (11.76 GPU-hours x 100 W at
$0.22/kWh). That is **29x**.

But marginal is the right comparison only because the host is a shared home
server that would be powered anyway. Its wall meter read 22.48 kWh for 21 days
of August — **$4.95, at an average draw of 44 W** — of which the analyses were
5%. Load the idle 42 W onto the trading bot and the two costs converge; leave
it as the shared overhead it is, and self-hosting wins by an order of
magnitude. Cost is therefore not the reason to move to a vendor. Speed is.

Also worth carrying forward: **a single-ticker sample understates the average.**
The 22 Aug GOOG run was 100k tokens; the nine-ticker sweep averaged 111k, with
several tickers at 106-137k. Estimating a sweep from one small run was
optimistic by about 10% before any pricing question.

Re-derive both the rate and these projections at the end of the comparison
week (started 2026-08-25, the first properly paired day).

## Vendored TradingAgents repo

It's a real nested git repo, registered as a **git submodule** of this repo
(`.gitmodules`, pinned to a commit via a `160000` gitlink) — this repo tracks
which TradingAgents commit is checked out without flattening its history.
`git clone` needs `--recurse-submodules` (or `git submodule update --init`
afterward) to populate it.

**Remote-naming gotcha**: a fresh submodule checkout only gets one remote,
named `origin`, pointing at whatever URL is in `.gitmodules` — that's the
`fork` (nandyalu/TradingAgentsUI), not upstream. The two-remote setup
described below (`origin` = TauricResearch upstream, `fork` = our fork) is
this particular working copy's local addition, done once when the branch was
first built; it does not survive a fresh clone. To restore it after a fresh
clone: `cd TradingAgents && git remote rename origin fork && git remote add
origin https://github.com/TauricResearch/TradingAgents.git && git fetch origin`.

Remotes (in a working copy that's had the above applied):

- `origin` = `https://github.com/TauricResearch/TradingAgents.git` — kept
  only as a reference point for diffing; do not push here.
- `fork` = `https://github.com/nandyalu/TradingAgentsUI.git` — our fork.
  Checked-out branch is `trading-helper-custom`, based on `fork/main`
  (itself a few commits ahead of the old v0.3.1 pin we used to track) plus 9
  commits cherry-picked from open upstream PRs that weren't merged yet but
  were judged worth having:

  - #1189 unparseable ratings surface as REVIEW instead of a silent Hold
  - #1200 avoid inventing arguments in opening debate turns
  - #1071 simplified vendor routing + CircuitBreaker for LLM vendor resilience
  - #1149 custom Ollama Modelfile guide (fast/accurate profiles)
  - #1074 retry an undecodable JSON response body instead of aborting the run
  - #1082 probability + risk/reward review on every trader proposal
  - #1134 Reddit OAuth2 (100 QPM) with automatic fallback to the RSS scraper
    when `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are unset. **The OAuth path
    is effectively dead for this project**: Reddit's Responsible Builder Policy
    ended self-serve API app creation, so those credentials can't be obtained
    for a personal tool. RSS is the supported path — see
    [docs/setup.md](docs/setup.md). Don't treat 429 warnings as a bug.
  - #1122 candidate screener script + trade-horizon-aware analysis prompts
  - plus one local fix-up commit resolving integration issues between the
    above (an `UnboundLocalError` in `sentiment_analyst.py` that was latent
    in #1134's own diff, plus two test fixtures)

  Full upstream test suite (606 passed, 2 pre-existing skips) and
  trading-helper's own `backend/tests/` (80 passed) were both green against this
  branch before it was pushed.

To check whether `fork/main` has moved (new commits merged upstream into the
fork) before assuming a bug needs a local fix: `cd TradingAgents && git fetch
fork && git log HEAD..fork/main --oneline`. Check `git log --stat` on any new
commits before merging — don't blind-merge, and re-apply the same care used
for the original cherry-picks if `fork/main` and `trading-helper-custom`
diverge further. Dependencies (including `tradingagents` itself, installed
non-editable from `./TradingAgents` — see root `pyproject.toml`'s
`[tool.uv.sources]`) are managed with `uv`: to pick up new commits made here
in trading-helper's own venv, just `uv sync` — it re-resolves the local path
dependency automatically, no manual reinstall needed.

After committing inside `TradingAgents/` (new cherry-picks, a rebase onto a
moved `fork/main`, etc.), the parent repo still points at the old commit
until you also commit the updated gitlink here: `git add TradingAgents && git
commit -m "..."` from the trading-helper root. `git status` at the root shows
`TradingAgents` as dirty/ahead whenever the two are out of sync.

## The auto trader: methodology, and a changelog

**This section is the record of what the agent is and how it got that way. Add
to the changelog whenever its behaviour changes — a reworded rule, a new number
in the prompt, a different limit. Behaviour is mostly prompt, so an experiment
that runs for a month across three prompt revisions has three experiments in it
and no way to tell them apart afterwards unless someone wrote down when the
question changed.**

Record the date, what changed, and **why**. The why is the part that stops the
same idea being re-proposed in three weeks, and it is the part nobody can
reconstruct later.

### What the agent is shown

One prompt per decision pass, assembled by `agent.build_prompt()`. In order:

1. **The regime line** when one is available — VIX, SPY against its 200-day
   average, the yield curve, as one sentence.
2. **The account**: total budget, uninvested cash, total equity with its return
   against the budget, realized profit. The *broker's* balance is never shown.
   The simulated account holds $1,000,000 and the agent is given a small
   fraction of it; if that number reached the prompt the budget would be
   meaningless.
3. **Holdings**, one line each: quantity, average cost, current price, market
   value, unrealized profit, share of the account, days held, what is resting
   at the broker under it, and what selling all of it would raise. A holding
   with no resting exit says `NOTHING is resting to close it` — the agent
   cannot move an exit it cannot see, nor notice one that was never placed.
4. **Recent analyst signals**, up to 12 from the last 3 days, filtered to the
   model the app is configured to use. Each carries the decision, the current
   price, the suggested entry, stop and target, the model's own chance of
   working, the risk/reward and the expected value in R-multiples — plus, in
   plain words, how many whole shares the cash could buy. That last part is
   computed in Python, because the model proposed $1,944 of buys against
   $1,000 of cash on a live run when it was left to do the arithmetic.
5. **Its own track record**: closed trades, how many were profitable, the net
   result, the average holding period, and the last six individually with what
   the analyst had said at entry. Once it has bought on a Hold signal twice, it
   is told how that worked out specifically — that being the pattern it
   actually falls into.
6. **The rules** (below), then the JSON shape to answer in.

### The rules, verbatim

The system message:

> You are a disciplined paper-trading portfolio manager. You answer with JSON
> only — no prose outside it. You never spend more cash than you have and never
> sell shares you do not hold.

The rules block:

- The buys you place must cost `$X` or less in total, added up across every buy.
  Not each — in total.
- Orders execute in the order you list them, so a sell frees its cash for a buy
  listed after it. To buy something you cannot currently afford, sell something
  first and put that sell earlier in the list.
- You may only sell shares you hold. No shorting, no options. Whole shares only.
- What the analysts' decisions mean: Buy means they expect it to rise. Sell
  means they expect it to fall, so exit it if you hold it. Hold means no action
  is recommended — if you do not own it, a Hold is not a reason to buy it.
- Some signals carry how good the analyst thought the bet was. [...] Signals
  without these numbers are not worse bets, only ones where the analyst did not
  say.
- You can also move the stop and take-profit on something you already hold,
  without buying or selling any of it. Use side `adjust` [...]
- Doing nothing is a valid answer, and often the right one.
- Before answering, add up what your buys cost and check it against your cash.

Three of those exist because of a specific failure and should not be trimmed as
padding: the total-not-each wording, the sell-to-fund ordering, and the
explanation of what a Hold means. Each was added after the model got that exact
thing wrong on a live run.

### What Python enforces, regardless of what the model says

The division is deliberate and load-bearing: **the model decides what and how
much; Python refuses what cannot be executed as stated, and never resizes.**
Resizing would quietly turn its decision into a different one, and then the
record would be of a strategy nobody chose.

- **Orders are screened against a running book, not the opening one.** Three
  buys that are each affordable alone are not necessarily affordable together.
- **An unaffordable order is dropped, not shrunk.**
- **Sells cannot exceed holdings** — and since the margin account will short
  where a cash account refuses, that is now enforced in `sandbox_broker` too
  rather than inherited from the account type.
- **Exit levels that would execute on placement are refused**: a stop at or
  above the price, a target at or below it.
- **A refused order is fed back once** and the model asked again, which is how
  it learns it may sell to fund a buy.

### How a position is opened and protected

A buy goes out as a **bracket**: a `MASTER` entry with `STOP_PROFIT` and
`STOP_LOSS` legs, one submission, one shared combo id. The broker activates the
exits when the entry fills, so the shares are never held with nothing under
them. The entry is a marketable limit rather than a market order because Webull
refuses a `MARKET` master — and the limit caps slippage, which matters on an
app-enforced budget.

When the stated stop is unusable, one is derived from 2×ATR(14) at the moment
of purchase. When a combo is refused — which happens routinely, because a cash
account will not accept one against unsettled funds — it falls back to a market
order plus separately-armed exits.

### The changelog

Newest first. Every entry says what changed and why.

**2026-08-26 — the agent chooses what to research.** A `side: "research"` action, and a menu of screened candidates in the prompt with what an analysis costs. This is the point of the analyst experiment: the live agent is measured on decisions given a fixed watchlist, and this one decides what is worth looking at at all. Commissioning a ticker adds it to the watchlist — which *is* the commission, since the morning sweep reads the watchlist. **The charge lands when the analysis runs, not when it is commissioned.** Billing at both ends charged a commissioned ticker twice, once for asking and once for the work; `propagate_ticker` already bills every ticker the sweep touches, including the held ones nobody commissioned, so that is the single place. The cost of this is that the agent can commission slightly more than its cash on a day the sweep has not happened yet — bounded by the daily cap to cents against a four-figure budget, and a far smaller problem than double-billing.

The menu is never free-form. A model naming its own tickers invents symbols, reaches illiquid things with no price data, and picks the day's pump; `candidates.py` already screens for liquidity and excludes anything up more than 30%, which matters because a raw screen once returned a stock up 927% and a price floor does not catch that — the pump is what lifted the price over the floor.

The answer arrives **tomorrow**, not in the same pass. That is the honest shape: an analyst does not hand over a report the instant you ask, and same-breath research would let the agent act with no cost to being wrong about what was worth studying. A daily cap of 15 applies regardless of cash, because money does not model time and the sweep has to finish before the open.

The whole section only appears when research is actually charged for. A menu the agent can take from for free is just a longer watchlist somebody else chose.

**2026-08-25 — the agent may move its own exits.** A `side: "adjust"` action,
with a new stop, target or both, on something already held. Before this, exits
were fixed when a position opened and untouched until it closed, so re-reading
a holding every morning taught the agent nothing it could act on short of
selling: GOOG spent a week with a $377.09 take-profit while each day's analysis
put the end of the move at $345.00. Python still refuses a level that would
execute on placement, and a level already where it was asked for is skipped
rather than re-sent.

**2026-08-25 — holdings now show what is resting under them.** The prompt lists
each position's live stop and target, and says `NOTHING is resting to close it`
when there is none. Added with the adjust action, and required by it: the agent
cannot sensibly move an exit it cannot see.

**2026-08-25 — signals are filtered to the configured model.** Running a second
model for comparison puts two signals per ticker in the table, sometimes
disagreeing. Without the filter the agent traded on the mixture, folding an
experiment into the live book.

**2026-08-25 — a conviction floor, switched off.** Minimum chance of working
and minimum risk/reward, both defaulting to zero. Off deliberately: the chance
of working is the model's own claim, and until the Scorecard's calibration says
it is honest *and* that it sorts outcomes, a threshold on it is arbitrary
discipline. A signal stating no number fails the floor rather than passing it,
or the floor could be dodged by not answering.

**2026-08-13 — buys go out as brackets.** Previously the exits were armed after
the buy returned, which meant they were validated while the account still held
nothing and read as a new short. Two positions were bought that day and neither
got its exits.

**2026-08-13 — an ATR stop is derived when the stated one is unusable.** Both
of that day's unprotected positions were bought days after their signal, by
which time the price had fallen through the stated stop and the level was
correctly discarded — leaving nothing. `record_signal` already substituted an
ATR stop, but only for Buy and Overweight, and the agent buys on Holds too.

**2026-08-13 — an unguarded position is announced.** It used to be silent: no
alert, no ledger row, and the only way to find out was to look at the broker.

### Before changing the prompt

Note the change here **first**, with the date and the reason. A month of runs
across an undocumented prompt revision cannot be analysed, and the temptation
to reconstruct the reasoning afterwards produces a story about what we would
like to have been thinking.

## Per-run cost telemetry

`backend/services/llm_usage.py` counts what each analysis spends: wall-clock
seconds, LLM calls, and prompt/completion tokens, stored on `Signal` and shown
in the Discord footer and the signal detail page. It exists to make the
self-host-vs-cloud decision arithmetic rather than guesswork, which is why the
token split by direction matters (cloud output tokens cost several times input
ones).

Two things about it are easy to get wrong:

- **The counts come from the provider's `usage` block, never a tokenizer
  estimate.** An estimate is wrong by exactly the amount that matters once it
  is multiplied by a price per million.
- **`UsageTracker` attaches to the two LLM client objects, not to a
  `propagate()` argument** — `propagate()` accepts no callbacks, and every
  agent, the debate, the reflector, and the signal processor all share
  `graph.deep_thinking_llm` / `graph.quick_thinking_llm`. Attaching there is
  what makes the count cover the whole run. A per-run tracker is safe because
  `_build_graph` already builds a fresh graph per analysis.

An unmeasured run stores NULL, never 0 — a zero would read as a free run.

## The model invents price levels (important)

`gemma4-e2b` reasons acceptably in prose but does not reliably carry concrete
figures into structured numeric fields. On 2026-08-06, 3 of 8 signals came back
with fabricated entry / stop / target levels:

| Ticker | Real price | Model's entry |
|---|---|---|
| GOOG | $356.62 | $2,000.00 |
| VERI | $1.26 | $4.50 |
| VERI | $1.25 | $30.00 |

The numbers look like **prices the model remembers from training** — $2,000 is
roughly pre-split GOOG, $30 roughly VERI's 2021 range. Two runs on the same
stock the same day produced entries 24× apart, so it is invention, not stale
data and not another ticker bleeding in. The market analyst's own report had
the right prices throughout; the *trader* stage was simply never given a price.

Two defenses, both in place:

1. **The trader now receives the deterministic snapshot.**
   `build_verified_market_snapshot` (computed in Python from the same OHLCV,
   never by a model) goes into the trader prompt, which explicitly forbids
   recalled prices and says to omit levels rather than guess.
2. **`analysis._trade_plan_levels` discards levels far from the traded price**,
   using `max_level_deviation_pct` per horizon (swing 35%, position 70%).
   `risk_reward` and `expected_value_r` go out with them, since TradingAgents
   computes both *from* those levels. `win_probability` survives — it is the
   model's own estimate, not a derivation.

Defense 2 is the one that must never be removed. A prompt cannot make a 2B
model reliable, and a fabricated stop is worse than no stop: the watchdog arms
an alert at a price the stock may never reach, or fires one immediately.

3. **`analysis._levels_on_the_wrong_side` drops a stop at or above the traded
   price and a target at or below it.** Defense 2 asks only how far a level is
   from the price, never which side of it the level is on, and the gap between
   those two questions is wide: 14 of the first 42 signals — a third of the
   book — held a level on the wrong side while every one of them sat inside the
   deviation tolerance. The shape is always the same. The model proposes a
   pullback entry, draws its stop and target around *that* entry, and the
   pullback never comes: ZBH on 2026-08-12 wanted to buy $91.00 with a $90.76
   stop and a $92.00 target while the stock traded at $97.89. All three levels
   are within 8% of the price and the plan is internally coherent — it is only
   the entry that never happened. Levels are read from the traded price
   forward, so a target under it is reached the instant it is stored and a stop
   over it triggers the same way. Nulling the stop also hands the signal to the
   ATR fallback in `_resolve_stop_loss`, which is how a Buy still ends up with
   a usable exit. Sell-ish decisions are exempt: this app is long-only, takes
   no action on them, and their levels point the other way by design.

`backend/scripts/scrub_implausible_levels.py` clears bad levels from rows
written before defense 2 existed; `backend/scripts/clear_wrong_side_levels.py`
does the same for defense 3. Both leave graded signals alone — grading read the
target to decide `price_target_hit`, so rewriting it afterwards would
contradict a verdict already given.

## Market data goes through the bar cache

`backend/services/bars.py` is a read-through cache over the `dailybar` table
(`(ticker, date)`). **Route any new daily-history read through `bars.get_bars()`,
not `yf.Ticker(...).history()`** — the whole point is that a completed session
never changes, so refetching one is waste and rate-limit risk.

Two legitimate direct yfinance uses remain, neither of them history:
`positions.get_current_price` (a quote, Webull's fallback) and
`watchdog.get_next_earnings_date` (the calendar).

Non-obvious rules the cache depends on:

- **Today's bar is never stored.** It is still moving. `include_today=True` gets
  it via a separate live request instead.
- **Pass `today=` when the caller has a market-relative date.** The watchdog
  does: after about 8pm ET the local clock is already tomorrow, so the default
  would treat the just-closed session as still in progress.
- **`_earliest_attempt` records what was asked for, not what came back.** Without
  it, a ticker with less history than requested refetches on every call forever.
- **`last_completed_session` ignores holidays deliberately.** The 30-minute
  recheck throttle absorbs the resulting extra request.

The table is pure cache; dropping it costs only a refetch.

## Webull OpenAPI reference

**<https://developer.webull.com/apis/llms.txt>** — an LLM-oriented index of the
whole OpenAPI documentation, with links to every endpoint page. Read it before
guessing at a Webull payload shape or endpoint name. The Python SDK
(`webull-openapi-python-sdk`) returns **raw dicts with no typed models**, so the
field names this repo relies on were discovered from live responses, not from
the package — the docs are the only other source of truth.

What the index covers, and where each maps here:

| Docs area | Used by |
|---|---|
| Account Management — Account List, Account Balance, Account Positions | `backend/services/broker.py` (`fetch_broker_positions`) |
| Market Data — snapshot, tick, depth, bars, fundamentals | `backend/services/quotes.py` (`get_realtime_price`) |
| Authentication — HMAC-SHA1 signature, client token lifecycle | `quotes.get_api_client`, token cached under `WEBULL_OPENAPI_TOKEN_DIR` |
| Order Management — preview/place/replace/cancel | **not used, deliberately.** Real order execution is a standing non-goal; access here is read-only |

### Combo orders: what the docs and `preview_order` both get wrong

The agent buys with a **bracket** — `MASTER` entry plus `STOP_PROFIT` and
`STOP_LOSS` legs, one `place_order` call, one shared `client_combo_order_id`.
The broker activates the exits when the entry fills, so no position is ever
held with nothing resting under it. Arming afterwards always had that window:
on 2026-08-13 both buys filled and neither got its exits, because the sell legs
were validated while the account still held nothing and read as a new short
(`GENERATE_NEW_SHORT_POSITION`).

Brackets are **not in `llms.txt`** — only the Place Order page's `combo_type`
enum mentions them. Four rules were found by testing against the live sandbox,
and none of them appear in the docs:

- A `MASTER` leg **cannot be `MARKET`**, and cannot be `GTC`
  (`INVALID_PARAMETER`). The entry is a marketable limit instead — 0.5% through
  the offer, `DAY` — which behaves like a market order and caps slippage.
- The exits **may be `GTC` under a `DAY` master**. They have to be: a `DAY`
  exit protects the position for an afternoon and then quietly stops existing.
- A stop at or above the entry limit is refused
  (`TRADE_STOP_LOSS_PRICE_LT_OPENPRICE`) — and the refusal takes the **buy**
  with it, because the legs are one submission. `agent._place` screens both
  levels before sending, so a bad level costs nothing.
- **Any combo is refused while the cash is unsettled**
  (`CANT_USE_UNSETTLE_FUNDS_FOR_COMBO_ORDER`). A plain market order may be
  placed against unsettled proceeds; a combo may not. Selling to fund a buy in
  the same pass is something the agent's prompt explicitly permits, so this is
  routine, not an edge case — `_place` falls back to a market order plus
  `_arm_exits` rather than failing the trade.

**`preview_order` cannot be used to check a combo.** It returned 200 for the
`MARKET` master that `place_order` then rejected outright. Preview validates
cost, not shape.

Two things the index settles that have bitten this project:

- It confirms there is **no news or social-sentiment endpoint**, so Webull
  cannot replace `get_news`/`reddit.py` no matter how the quota looks.
- It documents **MQTT streaming** for real-time data. This repo polls instead,
  which is the right call at a 1-2 week horizon, but it is the thing to reach
  for if intraday granularity ever matters.

Rate limits are not in the index itself — they live on the linked Market Data
API Overview page. Order History is documented at 2 requests per 2 seconds.

### Confirmed from the docs (2026-08-07)

**Account Positions** returns exactly: `position_id`, `currency`, `quantity`,
`symbol`, `option_strategy`, `instrument_type`, `last_price`, `cost_price`,
`unrealized_profit_loss`, `event_outcome`, `legs[]`. The four names
`broker._parse_position` relies on are correct.

**There is no acquisition-date field on a position.** Not under any name. This
makes `broker._parse_opened_at` dead code — it tries `open_date`,
`position_date`, `open_time` and others, and none of them can ever match, so
every synced holding falls through to the `(date unknown)` path and is excluded
from the vs-SPY comparison. It was written that way because the payload shape
had never been checked; the fallback is doing all the work.

**Order History is where the dates are**, and the sync now reads it
(`broker.fetch_order_fills` → `reconstruct_open_lots`). Three things about that
endpoint are not obvious and cost time to find:

- **Rows are combo wrappers, not orders.** Each row is
  `{client_order_id, combo_type, combo_order_id, orders: [...]}`, and a
  single-leg order is still wrapped in a one-element list. Read the top level
  and you find no symbol, no side, no quantity — every row parses to nothing.
  `broker.orders_in()` unwraps it.
- **`page_size` must be 10-100.** Anything outside that is HTTP 417,
  `OAUTH_OPENAPI_PARAM_ERR`.
- **The documented "2 requests per 2 seconds" is optimistic.** Pacing at exactly
  that returned 429s; `_ORDER_HISTORY_PAUSE` is 2.5s.

Verified against the live account 2026-08-07: 53 equity fills back to
2021-02-23. Dropped rows were all correct — unfilled orders, plus OPTION and
CRYPTO fills this equities-only app has no use for.

`fix_import_dates --from-webull` rebuilds already-imported holdings the same
way. Holdings with no fill (transferred in, or pre-2018) keep a date-unknown
remainder lot and stay out of the benchmark comparison rather than corrupting
it — which is also how a fractional dividend share is handled, since it never
came through an order.

## Tickers that stop trading

`backend/services/listings.py` marks a ticker inactive once no fresh bar has
appeared for `STALE_AFTER_TRADING_DAYS` (7). Every fetch path checks it: the bar
cache, `get_current_price`, the watchdog's tracked list, and the daily sweep.

**Why it needs detecting at all:** a delisted symbol does not fail cleanly.
AILEQ returned five bars across two months, every one priced at $0.000001.
Nothing in that looks like an error — to the bar cache it was a ticker merely
behind, so it refetched every 30 minutes forever, and the daily sweep spent
minutes of GPU analyzing a company with no market, then could not record the
signal because there was no price to record it against.

**The rule is freshness, not price.** A real penny stock at $0.0001 is still
real and must keep working; a price threshold would wrongly exclude it.

An inactive ticker is still rechecked once a day, so a lifted halt recovers
without anyone noticing. `/ignore` and `/unignore` are the manual override, and
a manual setting is never overwritten by detection.

A held position stays in the portfolio — there is just nothing to fetch, and its
lots are excluded from the vs-SPY comparison like any other undateable lot.

## Reddit/social-sentiment data source

`TradingAgents/tradingagents/dataflows/reddit.py` scrapes Reddit's public RSS
search feed (no API key). Occasional `429`/warning logs are expected and
handled gracefully (retry-once-with-backoff, then degrades to "no posts
found" for that subreddit) — not a bug unless it fails on *every* run.
`stocktwits.py` exists in the same directory as an unused alternative if
Reddit ever becomes unreliable enough to matter.

The Webull OpenAPI SDK (`backend/services/quotes.py`, `backend/services/broker.py`) is market-data +
brokerage only (quotes, fundamentals, financials, trading) — it has no
news-article or social-sentiment endpoints, so it can't replace
`get_news`/`reddit.py`.
