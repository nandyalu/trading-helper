"""Paper positions/equity-curve and the close-position action."""
from fastapi import APIRouter

from backend.database import db
from backend.api.schemas import ActionResultOut, PaperPortfolioOut, PaperSnapshotOut
from backend.services.paper import close_paper_position, get_paper_positions

router = APIRouter(prefix="/api/paper", tags=["paper"])


@router.get("", response_model=PaperPortfolioOut)
def get_paper():
    data = get_paper_positions()
    if data is None:
        return PaperPortfolioOut(
            positions=[], total_value=0.0, total_cost=0.0,
            total_unrealized=0.0, total_realized=0.0, missing_prices=[],
        )
    return PaperPortfolioOut.model_validate(data)


@router.get("/snapshots", response_model=list[PaperSnapshotOut])
def get_snapshots(limit: int = 90):
    return [PaperSnapshotOut.model_validate(s) for s in db.get_paper_snapshots(limit=limit)]


@router.post("/{ticker}/close", response_model=ActionResultOut)
def close_position(ticker: str):
    ticker = ticker.upper().strip()
    return ActionResultOut(message=close_paper_position(ticker))
