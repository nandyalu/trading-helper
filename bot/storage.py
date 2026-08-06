"""Tiny JSON-backed persistence for the watchlist and signal channel.

A single file is enough here — one bot process, low write frequency
(slash commands), no concurrent writers to race against.
"""
import json
import os

_STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "state.json")

_DEFAULT_STATE = {
    "watchlist": ["NVDA", "AAPL"],
    "channel_id": None,
    # {ticker: [{"side": "buy"|"sell", "date": "YYYY-MM-DD", "quantity": float, "price": float}, ...]}
    # Append-only transaction log — the single source of truth. Open lots, cost
    # basis, and realized P&L are all derived from this on read (see
    # bot/positions.py) rather than persisted as separately-mutated state.
    "positions": {},
}


def state_file_exists() -> bool:
    return os.path.exists(_STATE_PATH)


def load_state() -> dict:
    if not os.path.exists(_STATE_PATH):
        return dict(_DEFAULT_STATE)
    with open(_STATE_PATH) as f:
        state = json.load(f)
    return {**_DEFAULT_STATE, **state}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
