"""Market regime snapshot — reuses backend.services.regime.fetch_regime() directly,
already a pure, no-DB function returning a plain dataclass. The risk-on/
mixed/risk-off label is computed server-side via classify_regime() (the
same function format_regime_message() uses for Discord) rather than
duplicating its thresholds in the frontend."""
from fastapi import APIRouter

from backend.api.schemas import RegimeOut
from backend.services.regime import classify_regime, fetch_regime

router = APIRouter(prefix="/api/regime", tags=["regime"])


@router.get("", response_model=RegimeOut)
def get_regime():
    data = fetch_regime()
    label, emoji = classify_regime(data.vix, data.spy_vs_ma_pct, data.curve_spread_pct)
    return RegimeOut(
        as_of=data.as_of,
        vix=data.vix,
        spy_price=data.spy_price,
        spy_ma200=data.spy_ma200,
        curve_spread_pct=data.curve_spread_pct,
        spy_vs_ma_pct=data.spy_vs_ma_pct,
        label=label,
        emoji=emoji,
    )
