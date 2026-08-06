"""Real buy/sell transactions — mirrors bot/main.py's /buy, /sell commands
(bot/main.py:228-257)."""
from fastapi import APIRouter, HTTPException

from bot import db
from bot.api.schemas import ActionResultOut, TransactionIn
from bot.positions import compute_position

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.post("/buy", response_model=ActionResultOut)
def buy(payload: TransactionIn):
    ticker = payload.ticker.upper().strip()
    db.add_transaction(ticker, "buy", payload.price, payload.quantity)
    db.add_to_watchlist(ticker)
    position = compute_position(db.get_transactions(ticker))
    return ActionResultOut(
        message=(
            f"Bought {payload.quantity:g} {ticker} @ ${payload.price:,.2f}. "
            f"Position: {position.quantity:g} shares @ avg ${position.avg_cost:,.2f}."
        )
    )


@router.post("/sell", response_model=ActionResultOut)
def sell(payload: TransactionIn):
    ticker = payload.ticker.upper().strip()
    current_position = compute_position(db.get_transactions(ticker))
    if payload.quantity > current_position.quantity + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"You only hold {current_position.quantity:g} shares of {ticker}, can't sell {payload.quantity:g}.",
        )
    db.add_transaction(ticker, "sell", payload.price, payload.quantity)
    new_position = compute_position(db.get_transactions(ticker))
    return ActionResultOut(
        message=(
            f"Sold {payload.quantity:g} {ticker} @ ${payload.price:,.2f}. "
            f"Remaining: {new_position.quantity:g} shares. "
            f"Realized P&L to date: ${new_position.realized_pnl:,.2f}."
        )
    )
