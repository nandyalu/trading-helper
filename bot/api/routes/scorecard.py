"""Signal track record — reuses bot.scorecard.build_scorecard directly,
already a pure, DB-only function returning a plain dataclass (no extraction
needed, unlike paper.py/portfolio.py's embed builders)."""
from fastapi import APIRouter

from bot.api.schemas import ScorecardOut
from bot.scorecard import build_scorecard

router = APIRouter(prefix="/api/scorecard", tags=["scorecard"])


@router.get("", response_model=ScorecardOut)
def get_scorecard(ticker: str | None = None):
    stats = build_scorecard(ticker.upper().strip() if ticker else None)
    return ScorecardOut.model_validate(stats)
