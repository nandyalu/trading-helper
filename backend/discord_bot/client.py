"""The Discord connection. It sends; it does not take orders.

**There are no slash commands, and that is the design.** This app is one
autonomous agent trading one book, and every human lever was removed on
2026-09-01: no tracking a ticker by hand, no running an analysis on demand, no
buying or selling through a command. A control that lets a person nudge the
book makes the record a record of two decision-makers, and there is no way to
tell afterwards which one produced a result.

Discord's job here is to report. It carries what the agent decided and what
happened to its positions — not the analyses themselves, which run to thousands
of words each and are read on the Events and Signals pages where they can be
scrolled and compared.

When something does need correcting, the route is deliberate and slow: write
down what changed and why in JOURNEY.md's changelog, then make the correction
by hand. That costs a few minutes and leaves the experiment readable, which a
slash command does neither of.

``start_discord`` is a no-op without ``DISCORD_BOT_TOKEN``, so the rest of the
app runs the same with or without it.
"""
import asyncio
import logging
import os

import discord
from discord.ext import commands

from backend.discord_bot import notify

log = logging.getLogger("trading-bot.discord")

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    """Register the client with ``notify`` and nothing else.

    No command tree is synced, because there are no commands. A guild that
    still shows old ones is showing Discord's cache; they resolve to nothing
    and disappear on the next sync Discord performs.
    """
    notify.set_client(bot)
    log.info("Logged in as %s — reporting only, no commands", bot.user)


async def start_discord() -> None:
    """Run the bot as a background task on the caller's loop.

    Never ``bot.run()``, which blocks: this shares the loop with FastAPI and
    the scheduler.
    """
    if not BOT_TOKEN:
        log.info("DISCORD_BOT_TOKEN not set — running without Discord")
        return
    asyncio.create_task(bot.start(BOT_TOKEN), name="discord-client")


async def stop_discord() -> None:
    if BOT_TOKEN and not bot.is_closed():
        await bot.close()
    notify.set_client(None)
