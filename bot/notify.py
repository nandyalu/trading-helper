"""Optional Discord notification — a no-op when Discord isn't configured or
hasn't connected. Every scheduled job and the analyze routes call notify()
instead of resolving a channel and calling channel.send() directly, so the
same code path works identically whether or not DISCORD_BOT_TOKEN is set.
"""
import logging
import os

import discord

from bot import db

log = logging.getLogger("trading-bot.notify")

_DEFAULT_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID")

# Set once by bot/discord_client.py's start_discord() if DISCORD_BOT_TOKEN is
# configured; stays None (every notify() call below just no-ops) otherwise.
_client: discord.Client | None = None


def set_client(client: discord.Client | None) -> None:
    global _client
    _client = client


def resolve_channel_id() -> int | None:
    channel_id = db.get_setting("channel_id")
    if channel_id:
        return int(channel_id)
    if _DEFAULT_CHANNEL_ID:
        return int(_DEFAULT_CHANNEL_ID)
    return None


async def notify(message: str | None = None, embed: discord.Embed | None = None) -> discord.Message | None:
    """Posts to the configured Discord channel; returns the sent message, or
    None if Discord isn't connected, no channel is configured, or the send
    failed. Every call site already treats a None return as "no Discord
    side effect happened" (e.g. run_analysis_and_notify skips seeding the
    ✅ reaction), so callers never need to branch on whether Discord is on."""
    if _client is None:
        return None
    channel_id = resolve_channel_id()
    if channel_id is None:
        return None
    try:
        channel = _client.get_channel(channel_id) or await _client.fetch_channel(channel_id)
        return await channel.send(content=message, embed=embed)
    except discord.HTTPException:
        log.warning("Discord notify failed", exc_info=True)
        return None
