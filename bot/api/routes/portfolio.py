"""Real (Webull-synced) portfolio dashboard — same data as /portfolio in Discord."""
from fastapi import APIRouter

from bot.api.schemas import PortfolioOut
from bot.portfolio import get_portfolio_positions

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
def get_portfolio():
    data = get_portfolio_positions()
    if data is None:
        return PortfolioOut(
            positions=[], total_value=0.0, total_cost=0.0, total_realized=0.0,
            missing_prices=[], comparison=None, concentration=[],
        )
    return PortfolioOut.model_validate(data)
