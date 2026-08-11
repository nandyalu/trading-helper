"""The Discord bot — now an optional client, not the process owner. Slash
commands are thin wrappers over the same pure functions the web API and
scheduler use. start_discord()/stop_discord() are called from backend/app.py's
FastAPI lifespan; if DISCORD_BOT_TOKEN is unset, start_discord() is a no-op
and the rest of the app runs identically without it.
"""
import asyncio
import datetime
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from backend.database import db
from backend.discord_bot import notify
from backend.services import (
    agent,
    agent_book,
    agent_performance,
    candidates as candidates_service,
    analysis,
    ask,
    broker,
    digest,
    listings,
    paper,
    portfolio,
    quotes,
    regime,
    signals,
    sizing,
    watchdog,
)
from backend.services.positions import compute_position, describe_position, get_current_price
from backend.services.scorecard import build_scorecard, format_scorecard_embed

log = logging.getLogger("trading-bot.discord")

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    notify.set_client(bot)
    for guild in bot.guilds:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    log.info("Logged in as %s, synced commands to %d guild(s)", bot.user, len(bot.guilds))


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """✅ on one of the bot's analysis posts executes that signal as a paper
    trade. Raw event so it still works for messages posted before a restart.
    """
    if bot.user is not None and payload.user_id == bot.user.id:
        return  # ignore the seeded reaction itself
    if str(payload.emoji) != paper.PAPER_EMOJI:
        return
    signal = db.get_signal_by_message_id(str(payload.message_id))
    if signal is None:
        return  # a reaction on some unrelated message
    reply = await asyncio.to_thread(paper.execute_signal_reaction, signal)
    channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
    await channel.send(reply)


@bot.tree.command(description="Add a ticker to the tracked watchlist")
@app_commands.describe(ticker="Stock ticker, e.g. NVDA")
async def track(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    if ticker in db.get_watchlist():
        await interaction.response.send_message(f"{ticker} is already tracked.", ephemeral=True)
        return
    db.add_to_watchlist(ticker)
    await interaction.response.send_message(f"Tracking {ticker}.")


@bot.tree.command(description="Remove a ticker from the tracked watchlist")
@app_commands.describe(ticker="Stock ticker, e.g. NVDA")
async def untrack(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    if ticker not in db.get_watchlist():
        await interaction.response.send_message(f"{ticker} isn't tracked.", ephemeral=True)
        return
    db.remove_from_watchlist(ticker)
    await interaction.response.send_message(f"Stopped tracking {ticker}.")


@bot.tree.command(description="List currently tracked tickers")
async def watchlist(interaction: discord.Interaction):
    tickers = db.get_watchlist()
    if not tickers:
        await interaction.response.send_message("Watchlist is empty.")
        return
    await interaction.response.send_message(", ".join(tickers))


@bot.tree.command(description="Record a buy transaction")
@app_commands.describe(ticker="Stock ticker, e.g. NVDA", price="Price per share", quantity="Number of shares")
async def buy(interaction: discord.Interaction, ticker: str, price: float, quantity: float):
    ticker = ticker.upper().strip()
    db.add_transaction(ticker, "buy", price, quantity)
    db.add_to_watchlist(ticker)
    position = compute_position(db.get_transactions(ticker))
    await interaction.response.send_message(
        f"Bought {quantity:g} {ticker} @ ${price:,.2f}. "
        f"Position: {position.quantity:g} shares @ avg ${position.avg_cost:,.2f}."
    )


@bot.tree.command(description="Record a sell transaction")
@app_commands.describe(ticker="Stock ticker, e.g. NVDA", price="Price per share", quantity="Number of shares")
async def sell(interaction: discord.Interaction, ticker: str, price: float, quantity: float):
    ticker = ticker.upper().strip()
    current_position = compute_position(db.get_transactions(ticker))
    if quantity > current_position.quantity + 1e-9:
        await interaction.response.send_message(
            f"You only hold {current_position.quantity:g} shares of {ticker}, can't sell {quantity:g}.",
            ephemeral=True,
        )
        return
    db.add_transaction(ticker, "sell", price, quantity)
    new_position = compute_position(db.get_transactions(ticker))
    await interaction.response.send_message(
        f"Sold {quantity:g} {ticker} @ ${price:,.2f}. Remaining: {new_position.quantity:g} shares. "
        f"Realized P&L to date: ${new_position.realized_pnl:,.2f}."
    )


@bot.tree.command(description="List your current stock positions")
async def positions(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    held = {t: compute_position(db.get_transactions(t)) for t in db.get_all_transaction_tickers()}
    held = {t: p for t, p in held.items() if p.quantity > 0}
    if not held:
        await interaction.followup.send("No open positions.")
        return
    embed = discord.Embed(title="Your Positions", timestamp=datetime.datetime.now(datetime.timezone.utc))
    for ticker, position in held.items():
        embed.add_field(name=ticker, value="\n".join(describe_position(ticker, position)), inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(description="List recent tracked signals and their outcomes")
@app_commands.describe(ticker="Optional: filter to one ticker")
async def signals(interaction: discord.Interaction, ticker: str | None = None):
    ticker = ticker.upper().strip() if ticker else None
    rows = db.get_recent_signals(ticker=ticker, limit=10)
    if not rows:
        await interaction.response.send_message("No signals recorded yet.")
        return
    embed = discord.Embed(title="Recent Signals" + (f" — {ticker}" if ticker else ""))
    for row in rows:
        outcome = row.outcome.upper() if row.outcome else "PENDING"
        value = f"{row.decision} on {row.signal_date} @ ${row.price_at_signal:,.2f} — {outcome}"
        if row.outcome:
            value += f" (now ${row.price_at_evaluation:,.2f})"
        if row.outcome_vs_benchmark:
            value += f" · vs SPY {row.outcome_vs_benchmark.upper()}"
        embed.add_field(name=row.ticker, value=value, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Win-rate scorecard of past signals (absolute and vs SPY)")
@app_commands.describe(ticker="Optional: filter to one ticker")
async def scorecard(interaction: discord.Interaction, ticker: str | None = None):
    ticker = ticker.upper().strip() if ticker else None
    await interaction.response.defer(thinking=True)
    stats = await asyncio.to_thread(build_scorecard, ticker)
    if stats.resolved == 0:
        suffix = f" ({stats.pending} pending)" if stats.pending else ""
        await interaction.followup.send(f"No resolved signals yet{suffix}.")
        return
    await interaction.followup.send(embed=format_scorecard_embed(stats, ticker))


@bot.tree.command(name="paper", description="Show the paper-trading portfolio")
async def paper_portfolio(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    embed = await asyncio.to_thread(paper.build_paper_embed)
    if embed is None:
        await interaction.followup.send(
            f"No paper trades yet — react {paper.PAPER_EMOJI} to an analysis post to take one."
        )
        return
    await interaction.followup.send(embed=embed)


@bot.tree.command(description="Close an open paper position at the current price")
@app_commands.describe(ticker="Stock ticker, e.g. NVDA")
async def paperclose(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    await interaction.response.defer(thinking=True)
    reply = await asyncio.to_thread(paper.close_paper_position, ticker)
    await interaction.followup.send(reply)


@bot.tree.command(description="Set the dollar amount each paper buy uses")
@app_commands.describe(amount="Notional dollars per paper buy, e.g. 1000")
async def papersize(interaction: discord.Interaction, amount: float):
    if not 0 < amount <= 1_000_000:
        await interaction.response.send_message(
            "Amount must be between $0 and $1,000,000.", ephemeral=True
        )
        return
    paper.set_notional(amount)
    await interaction.response.send_message(f"Paper buys will now use ${amount:,.2f} each.")


@bot.tree.command(name="portfolio", description="Portfolio dashboard: weights, P&L, and performance vs SPY")
async def portfolio_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    embed = await asyncio.to_thread(portfolio.build_portfolio_embed)
    if embed is None:
        await interaction.followup.send("No transactions recorded yet — use /buy to add one.")
        return
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="digest", description="The weekly digest, on demand")
async def digest_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    embed = await asyncio.to_thread(digest.build_weekly_digest_embed)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="regime", description="Market regime snapshot: VIX, SPY vs 200-day, yield curve")
async def regime_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    data = await asyncio.to_thread(regime.fetch_regime)
    await interaction.followup.send(regime.format_regime_message(data))


@bot.tree.command(description="Sync watchlist and positions from your Webull account now")
async def webullsync(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    if not broker.is_configured():
        await interaction.followup.send("Webull keys aren't configured — add them to .env first.")
        return
    summary = await asyncio.to_thread(broker.run_sync)
    if summary is None:
        await interaction.followup.send("Couldn't reach the Webull account API — check the logs.")
        return
    await interaction.followup.send(summary)


@bot.tree.command(name="ask", description="Ask a question about a ticker's latest analysis")
@app_commands.describe(ticker="Stock ticker, e.g. NVDA", question="e.g. What did the bear case say?")
async def ask_cmd(interaction: discord.Interaction, ticker: str, question: str):
    ticker = ticker.upper().strip()
    await interaction.response.defer(thinking=True)
    try:
        answer = await asyncio.to_thread(ask.answer_about_ticker, ticker, question)
    except Exception as exc:
        log.exception("/ask failed for %s", ticker)
        await interaction.followup.send(f"Couldn't answer that: {exc}")
        return
    embed = discord.Embed(title=f"{ticker} — {question[:200]}", description=answer[:4096])
    await interaction.followup.send(embed=embed)


@bot.tree.command(description="View or set account equity and the limits used for sizing suggestions")
@app_commands.describe(
    equity="Account equity in dollars, e.g. 5000",
    risk_pct="Percent of equity to risk per trade (default 1)",
    max_position_pct="Ceiling on one position, as a percent of equity (default 20)",
    max_positions="How many names may be open at once (default 5)",
)
async def risk(
    interaction: discord.Interaction,
    equity: float | None = None,
    risk_pct: float | None = None,
    max_position_pct: float | None = None,
    max_positions: int | None = None,
):
    if equity is not None and equity <= 0:
        await interaction.response.send_message("Equity must be positive.", ephemeral=True)
        return
    if risk_pct is not None and not 0 < risk_pct <= 10:
        await interaction.response.send_message("Risk % must be between 0 and 10.", ephemeral=True)
        return
    if max_position_pct is not None and not 0 < max_position_pct <= 100:
        await interaction.response.send_message("Max position % must be between 0 and 100.", ephemeral=True)
        return
    if max_positions is not None and not 1 <= max_positions <= 50:
        await interaction.response.send_message("Max positions must be between 1 and 50.", ephemeral=True)
        return
    sizing.set_risk_settings(equity, risk_pct, max_position_pct, max_positions)
    current_equity, current_pct = sizing.get_risk_settings()
    cap_pct = sizing.get_max_position_pct()
    slots = sizing.get_max_positions()
    if current_equity is None:
        await interaction.response.send_message(
            f"Risk per trade: {current_pct:g}% · at most {cap_pct:g}% per position · "
            f"up to {slots} positions.\nNo account equity set yet, so Buy embeds show only "
            "the ATR stop. Set it with /risk equity:5000."
        )
    else:
        await interaction.response.send_message(
            f"Sizing uses {current_pct:g}% risk on ${current_equity:,.0f} equity "
            f"(~${current_equity * current_pct / 100:,.0f} per trade between entry and stop), "
            f"capped at ${current_equity * cap_pct / 100:,.0f} per position "
            f"({cap_pct:g}%), across at most {slots} positions."
        )


@bot.tree.command(description="Run TradingAgents on a ticker right now")
@app_commands.describe(ticker="Stock ticker, e.g. NVDA")
async def analyze(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    await interaction.response.send_message(f"Started analysis for {ticker}, this may take a few minutes...")
    try:
        final_state, decision = await analysis.propagate_ticker(ticker)
    except Exception as exc:
        log.exception("Analysis failed for %s", ticker)
        await interaction.followup.send(f"Analysis failed for {ticker}: {exc}")
        return
    position = compute_position(db.get_transactions(ticker))
    sizing_field = await asyncio.to_thread(sizing.build_sizing_field, ticker, decision)
    price = await asyncio.to_thread(get_current_price, ticker)
    message = await interaction.followup.send(
        embed=analysis.format_decision_embed(
            ticker, final_state, decision, position, sizing_field, price
        )
    )
    analysis.record_signal(ticker, final_state, decision, message_id=str(message.id))
    try:
        await message.add_reaction(paper.PAPER_EMOJI)
    except discord.HTTPException:
        log.warning("Couldn't seed the ✅ reaction (missing Add Reactions permission?)")


@bot.tree.command(description="Set this channel as the destination for daily signals")
@app_commands.default_permissions(manage_guild=True)
async def setchannel(interaction: discord.Interaction):
    db.set_setting("channel_id", str(interaction.channel_id))
    await interaction.response.send_message(f"Daily signals will post in {interaction.channel.mention}.")


@bot.tree.command(description="View or set intraday alert thresholds")
@app_commands.describe(
    move_pct="Daily % move that alerts and triggers an analysis (default 5)",
    stop_pct="% drop below avg cost that fires a stop alert (default 10)",
    volume_mult="Multiple of the 20-day average volume that counts as unusual (default 2)",
    enabled="Turn the intraday watchdog on or off",
)
async def alertconfig(
    interaction: discord.Interaction,
    move_pct: float | None = None,
    stop_pct: float | None = None,
    volume_mult: float | None = None,
    enabled: bool | None = None,
):
    for key, value in (
        ("alert_move_pct", move_pct),
        ("alert_stop_pct", stop_pct),
        ("alert_volume_mult", volume_mult),
    ):
        if value is not None:
            if value <= 0:
                await interaction.response.send_message("Thresholds must be positive.", ephemeral=True)
                return
            db.set_setting(key, str(value))
    if enabled is not None:
        db.set_setting("alerts_enabled", "on" if enabled else "off")
    config = watchdog.load_config()
    await interaction.response.send_message(
        f"Watchdog **{'on' if config.enabled else 'off'}** · move ≥ {config.move_pct:g}% · "
        f"stop {config.stop_pct:g}% below avg cost · volume ≥ {config.volume_mult:g}× 20-day avg."
    )


@bot.tree.command(description="Turn the fixed daily watchlist sweep on or off")
@app_commands.describe(enabled="off = event-triggered analyses only; signal evaluation still runs daily")
async def dailysweep(interaction: discord.Interaction, enabled: bool):
    db.set_setting("daily_sweep", "on" if enabled else "off")
    if enabled:
        await interaction.response.send_message("Daily watchlist sweep is **on** (21:30 UTC weekdays).")
    else:
        await interaction.response.send_message(
            "Daily watchlist sweep is **off** — analyses now run only on triggers "
            "(earnings, big moves, volume) or /analyze. Signal evaluation still runs daily."
        )


@bot.tree.command(description="Skip a ticker that has no usable market data, or un-skip one")
@app_commands.describe(
    ticker="Ticker symbol",
    skip="True = never fetch or analyze it · False = follow it normally",
)
async def ignore(interaction: discord.Interaction, ticker: str, skip: bool = True):
    """Manual override for the delisted/halted detection.

    Detection handles the common case on its own. This is for the two it gets
    wrong: a thinly traded name the user wants followed anyway, and a ticker
    they simply do not want spending GPU time.
    """
    ticker = ticker.upper().strip()
    listings.set_manual(ticker, inactive=skip, reason="manually ignored" if skip else None)
    if skip:
        await interaction.response.send_message(
            f"**{ticker}** is now skipped — no price fetches, no alerts, no scheduled analysis. "
            f"Any position you hold still shows in /portfolio. Undo with `/ignore {ticker} skip:False`."
        )
    else:
        await interaction.response.send_message(
            f"**{ticker}** is followed normally again, and detection will no longer override that. "
            f"Use `/unignore {ticker}` to hand it back to automatic detection."
        )


@bot.tree.command(description="Hand a ticker back to automatic delisted/halted detection")
@app_commands.describe(ticker="Ticker symbol")
async def unignore(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper().strip()
    listings.clear_manual(ticker)
    await interaction.response.send_message(
        f"**{ticker}** is back on automatic detection — it will be skipped only if it stops "
        f"producing bars for {listings.STALE_AFTER_TRADING_DAYS} trading days."
    )


@bot.tree.command(description="Set the trade horizon every analysis runs at")
@app_commands.describe(horizon="swing = 1-2 week trades · position = multi-month holds")
@app_commands.choices(
    horizon=[
        app_commands.Choice(name="swing (1-2 weeks)", value="swing"),
        app_commands.Choice(name="position (multi-month)", value="position"),
    ]
)
async def horizon(interaction: discord.Interaction, horizon: app_commands.Choice[str]):
    analysis.set_horizon(horizon.value)
    params = signals.horizon_params(horizon.value)
    await interaction.response.send_message(
        f"Trade horizon set to **{horizon.value}** — signals are graded after "
        f"{params['eval_days']} days by default, and a Hold passes while price "
        f"stays within ±{params['hold_band_pct']:g}%.\n"
        "Signals already recorded keep the horizon they were made under."
    )


async def _model_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete rather than fixed choices: the list is whatever the LLM
    endpoint has pulled, which changes without a redeploy. Discord caps a
    response at 25 options."""
    models = await asyncio.to_thread(analysis.list_models)
    matches = [name for name in models if current.lower() in name.lower()]
    return [app_commands.Choice(name=name[:100], value=name) for name in matches[:25]]


@bot.tree.command(description="Choose the LLM every analysis runs on")
@app_commands.describe(model="Leave blank to see the current model and what else is available")
@app_commands.autocomplete(model=_model_autocomplete)
async def model(interaction: discord.Interaction, model: str | None = None):
    await interaction.response.defer()
    if model is None:
        available = await asyncio.to_thread(analysis.list_models)
        current = await asyncio.to_thread(analysis.get_model)
        lines = [f"Analysis runs on **{current}**."]
        if available:
            lines.append("Available: " + ", ".join(f"`{name}`" for name in available))
        else:
            lines.append("Couldn't reach the LLM endpoint to list the alternatives.")
        await interaction.followup.send("\n".join(lines))
        return
    try:
        await asyncio.to_thread(analysis.set_model, model)
    except ValueError as exc:
        await interaction.followup.send(str(exc))
        return
    await interaction.followup.send(
        f"Analysis now runs on **{model}**. Signals already recorded keep the model "
        "they were made with, so /scorecard can compare the two."
    )


# Named explicitly: the handler can't be called `agent` because the module of
# that name is imported above, and discord.py takes the command name from the
# function otherwise.
@bot.tree.command(name="agent", description="The paper-trading agent's book, or run/stop it")
@app_commands.describe(
    action="Leave blank to see the book. on/off switches the agent; run decides now.",
    budget="Set the agent's budget in dollars (only with action:on)",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="on — let it trade each morning", value="on"),
        app_commands.Choice(name="off — stop trading", value="off"),
        app_commands.Choice(name="run — decide right now", value="run"),
    ]
)
async def agent_command(
    interaction: discord.Interaction,
    action: app_commands.Choice[str] | None = None,
    budget: float | None = None,
):
    await interaction.response.defer()
    if budget is not None:
        try:
            await asyncio.to_thread(agent_book.set_budget, budget)
        except ValueError as exc:
            await interaction.followup.send(str(exc))
            return

    if action is None or action.value not in ("on", "off", "run"):
        book = await asyncio.to_thread(agent_book.build_book, get_current_price)
        state = "on" if await asyncio.to_thread(agent.is_enabled) else "off"
        lines = [
            f"Paper agent is **{state}** on a ${book.budget:,.0f} budget.",
            f"Equity **${book.equity:,.2f}** ({book.return_pct:+.1f}%) · "
            f"cash ${book.cash:,.2f} · realized ${book.realized_pnl:+,.2f}",
        ]
        for h in book.holdings:
            price = f"${h.price:,.2f}" if h.price is not None else "unpriced"
            lines.append(f"- {h.ticker}: {h.quantity:g} @ ${h.avg_cost:,.2f} avg, now {price}")
        # The comparison is the point of the whole exercise, so it goes in the
        # default view rather than behind another command.
        comparison = await asyncio.to_thread(agent_performance.compare)
        if comparison.strategies:
            lines.append("")
            lines.append(f"**{comparison.verdict}**")
            for strategy in comparison.strategies:
                lines.append(
                    f"- {strategy.name}: ${strategy.equity:,.2f} "
                    f"({strategy.return_pct(comparison.budget):+.1f}%, "
                    f"{strategy.trades} trade(s))"
                )
        await interaction.followup.send("\n".join(lines))
        return

    if action.value == "run":
        run = await asyncio.to_thread(agent.run_once)
        await interaction.followup.send(embed=agent.format_run_embed(run))
        return

    enabled = action.value == "on"
    if enabled and not quotes.is_sandbox():
        await interaction.followup.send(
            "Webull is not in sandbox mode, so the agent would refuse every order. "
            "Not switching it on."
        )
        return
    await asyncio.to_thread(agent.set_enabled, enabled)
    await interaction.followup.send(
        f"Paper agent **{'on' if enabled else 'off'}**"
        + (f", budget ${budget:,.0f}." if budget is not None else ".")
        + (" It decides each weekday at 13:35 UTC, just after the US open." if enabled else "")
    )


@bot.tree.command(name="candidates", description="Screened tickers worth considering following")
async def candidates_command(interaction: discord.Interaction):
    await interaction.response.defer()
    found = await asyncio.to_thread(candidates_service.fetch_candidates)
    await interaction.followup.send(candidates_service.format_candidates(found))


async def start_discord() -> None:
    """No-op if DISCORD_BOT_TOKEN is unset — the rest of the app runs the
    same either way. Runs the bot as a background task on the caller's loop
    (never bot.run(), which blocks) so it shares the loop with FastAPI/quiv."""
    if not BOT_TOKEN:
        log.info("DISCORD_BOT_TOKEN not set — running without Discord")
        return
    asyncio.create_task(bot.start(BOT_TOKEN), name="discord-client")


async def stop_discord() -> None:
    if BOT_TOKEN and not bot.is_closed():
        await bot.close()
    notify.set_client(None)
