"""One-time import of the old JSON-file state (bot/storage.py) into the new
SQLite tables. Runs once at startup; a no-op once the DB has any watchlist
rows, so it's safe to call on every start. The original state.json is left in
place afterward (untouched) as an extra safety net alongside the pre-deploy
backup taken before this shipped.
"""
import datetime
import logging

from bot import db
from bot.storage import load_state, state_file_exists

log = logging.getLogger("trading-bot")


def migrate_if_needed() -> None:
    if not state_file_exists():
        return  # fresh install, nothing to import — must check the file, not
        # load_state()'s return value, since that always fills in non-empty
        # defaults (["NVDA", "AAPL"]) even when no file is present.
    if db.get_watchlist():
        return  # already migrated (or a fresh DB that's since been used normally)

    state = load_state()
    log.info("Migrating legacy state.json into the SQLite DB")
    for ticker in state["watchlist"]:
        db.add_to_watchlist(ticker)
    for ticker, transactions in state["positions"].items():
        for tx in transactions:
            db.add_transaction(
                ticker,
                tx["side"],
                tx["price"],
                tx["quantity"],
                date=datetime.date.fromisoformat(tx["date"]),
            )
    if state["channel_id"]:
        db.set_setting("channel_id", str(state["channel_id"]))
    log.info(
        "Migration complete: %d watchlist ticker(s), %d ticker(s) with transactions",
        len(state["watchlist"]),
        len(state["positions"]),
    )
