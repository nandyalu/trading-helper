"""Grouped settings — mirrors /papersize, /risk, /alertconfig, /dailysweep,
and the /webullsync action (backend/discord_bot/client.py:187, 251, 307, 340, 223).
All the underlying getters/setters are already pure BotSetting reads/writes;
this just gives them one JSON shape instead of four Discord commands."""
from fastapi import APIRouter, HTTPException

from backend.database import db
from backend.services import agent, agent_book, analysis, broker, paper, quotes, sizing, watchdog
from backend.api.schemas import ActionResultOut, SettingsOut, SettingsPatchIn

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _current_settings() -> SettingsOut:
    equity, risk_pct = sizing.get_risk_settings()
    alerts = watchdog.load_config()
    return SettingsOut(
        horizon=analysis.get_horizon(),
        llm_model=analysis.get_model(),
        llm_model_choices=analysis.model_choices(),
        paper_notional=paper.get_notional(),
        risk_equity=equity,
        risk_pct=risk_pct,
        max_position_pct=sizing.get_max_position_pct(),
        max_positions=sizing.get_max_positions(),
        alert_move_pct=alerts.move_pct,
        alert_stop_pct=alerts.stop_pct,
        alert_volume_mult=alerts.volume_mult,
        alerts_enabled=alerts.enabled,
        daily_sweep_enabled=db.get_setting("daily_sweep") != "off",
        agent_enabled=agent.is_enabled(),
        agent_budget=agent_book.get_budget(),
        agent_min_win_probability=agent.get_conviction()[0],
        agent_min_risk_reward=agent.get_conviction()[1],
    )


@router.get("", response_model=SettingsOut)
def get_settings():
    return _current_settings()


@router.patch("", response_model=SettingsOut)
def update_settings(payload: SettingsPatchIn):
    if payload.horizon is not None:
        try:
            analysis.set_horizon(payload.horizon)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.llm_model is not None:
        try:
            analysis.set_model(payload.llm_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.paper_notional is not None:
        if not 0 < payload.paper_notional <= 1_000_000:
            raise HTTPException(status_code=400, detail="Paper notional must be between $0 and $1,000,000.")
        paper.set_notional(payload.paper_notional)

    if payload.risk_equity is not None and payload.risk_equity <= 0:
        raise HTTPException(status_code=400, detail="Equity must be positive.")
    if payload.risk_pct is not None and not 0 < payload.risk_pct <= 10:
        raise HTTPException(status_code=400, detail="Risk % must be between 0 and 10.")
    if payload.max_position_pct is not None and not 0 < payload.max_position_pct <= 100:
        raise HTTPException(status_code=400, detail="Max position % must be between 0 and 100.")
    if payload.max_positions is not None and not 1 <= payload.max_positions <= 50:
        raise HTTPException(status_code=400, detail="Max positions must be between 1 and 50.")
    if any(
        value is not None
        for value in (payload.risk_equity, payload.risk_pct, payload.max_position_pct, payload.max_positions)
    ):
        sizing.set_risk_settings(
            payload.risk_equity, payload.risk_pct, payload.max_position_pct, payload.max_positions
        )

    for key, value in (
        ("alert_move_pct", payload.alert_move_pct),
        ("alert_stop_pct", payload.alert_stop_pct),
        ("alert_volume_mult", payload.alert_volume_mult),
    ):
        if value is not None:
            if value <= 0:
                raise HTTPException(status_code=400, detail="Thresholds must be positive.")
            db.set_setting(key, str(value))

    if payload.alerts_enabled is not None:
        db.set_setting("alerts_enabled", "on" if payload.alerts_enabled else "off")
    if payload.daily_sweep_enabled is not None:
        db.set_setting("daily_sweep", "on" if payload.daily_sweep_enabled else "off")

    if payload.agent_budget is not None:
        try:
            agent_book.set_budget(payload.agent_budget)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.agent_min_win_probability is not None or payload.agent_min_risk_reward is not None:
        try:
            agent.set_conviction(
                payload.agent_min_win_probability, payload.agent_min_risk_reward
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.agent_enabled is not None:
        # Switching the agent on outside the sandbox would arm something that
        # refuses every order anyway; saying so beats an agent that silently
        # never trades.
        if payload.agent_enabled and not quotes.is_sandbox():
            raise HTTPException(
                status_code=400,
                detail="Webull is not in sandbox mode — the agent would refuse every order.",
            )
        agent.set_enabled(payload.agent_enabled)

    return _current_settings()


@router.post("/webull-sync", response_model=ActionResultOut)
def webull_sync():
    if not broker.is_configured():
        raise HTTPException(status_code=400, detail="Webull keys aren't configured — add them to .env first.")
    summary = broker.run_sync()
    if summary is None:
        raise HTTPException(status_code=502, detail="Couldn't reach the Webull account API — check the logs.")
    return ActionResultOut(message=summary)
