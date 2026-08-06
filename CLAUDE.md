# trading-helper — Claude Code context

Discord bot (`bot/`) delegating analysis to a vendored multi-agent framework
(`TradingAgents/`, its own git repo cloned from
`https://github.com/TauricResearch/TradingAgents.git`, currently pinned to
v0.3.1). This top-level directory itself is **not** a git repo. See
[README.md](README.md) and [docs/overview.md](docs/overview.md) for
architecture/commands — this file only covers what those don't.

## Deployment topology (important, non-obvious)

Two copies of the compose config exist and are **not synced automatically**:

- [dockge/trading-bot.compose.yaml](dockge/trading-bot.compose.yaml) — tracked
  in this repo, the source-of-truth template. Edit this one.
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

**Known-bad model:** `gemma4:e2b` previously hit a `GraphRecursionError` on
ZBH (never terminated its reasoning loop) — `qwen3:latest` is the working
Ollama default. Comment preserved in the compose file; don't switch back to
gemma without expecting that failure mode.

**Gemini capacity note (2026-07-30):** `gemini-3.5-flash` returned 100%
persistent `503 UNAVAILABLE` ("high demand") over ~12h straight — looked
like a tier/capacity issue with that specific just-GA'd model, not a
transient blip. `gemini-3.1-flash-lite` worked reliably (16/16 calls
succeeded), ran a full analysis in <1 min vs Ollama's ~15 min, at roughly
$0.02–0.08/analysis. If revisiting Gemini, start with `flash-lite`, not
`3.5-flash`.

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
    when `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are unset — see
    [docs/setup.md](docs/setup.md) for how to get those
  - #1122 candidate screener script + trade-horizon-aware analysis prompts
  - plus one local fix-up commit resolving integration issues between the
    above (an `UnboundLocalError` in `sentiment_analyst.py` that was latent
    in #1134's own diff, plus two test fixtures)

  Full upstream test suite (606 passed, 2 pre-existing skips) and
  trading-helper's own `bot/tests/` (80 passed) were both green against this
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

## Reddit/social-sentiment data source

`TradingAgents/tradingagents/dataflows/reddit.py` scrapes Reddit's public RSS
search feed (no API key). Occasional `429`/warning logs are expected and
handled gracefully (retry-once-with-backoff, then degrades to "no posts
found" for that subreddit) — not a bug unless it fails on *every* run.
`stocktwits.py` exists in the same directory as an unused alternative if
Reddit ever becomes unreliable enough to matter.

The Webull OpenAPI SDK (`bot/quotes.py`, `bot/broker.py`) is market-data +
brokerage only (quotes, fundamentals, financials, trading) — it has no
news-article or social-sentiment endpoints, so it can't replace
`get_news`/`reddit.py`.
