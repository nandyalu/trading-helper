"""Signal track record — reuses backend.services.scorecard.build_scorecard directly,
already a pure, DB-only function returning a plain dataclass (no extraction
needed)."""
from fastapi import APIRouter

from backend.api.schemas import CalibrationBandOut, CalibrationOut, ScorecardOut
from backend.services.calibration import build_calibration
from backend.services.scorecard import build_scorecard

router = APIRouter(prefix="/api/scorecard", tags=["scorecard"])


@router.get("", response_model=ScorecardOut)
def get_scorecard(ticker: str | None = None):
    stats = build_scorecard(ticker.upper().strip() if ticker else None)
    return ScorecardOut.model_validate(stats)


@router.get("/calibration", response_model=CalibrationOut)
def get_calibration():
    """Does the model's stated confidence match how often it is right?

    Not filtered by ticker. Calibration is a property of the model, and a
    handful of signals on one stock says nothing about it.
    """
    result = build_calibration()
    return CalibrationOut(
        resolved=result.resolved,
        passes=result.passes,
        stated_pct=result.stated_pct,
        actual_pct=result.actual_pct,
        gap=result.gap,
        sorts_outcomes=result.sorts_outcomes,
        verdict=result.verdict,
        bands=[CalibrationBandOut.model_validate(b) for b in result.populated_bands],
    )
