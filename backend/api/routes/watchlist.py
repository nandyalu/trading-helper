"""The watchlist, read-only.

**Nothing here adds or removes a ticker, and that is the design.** The agent
chooses what it watches: it commissions research with a ``research`` action and
drops a name with an ``untrack`` action, and it pays for every ticker on the
list every morning. A hand-added ticker would appear in that record as a name
the agent chose and never chose, and no reading of the book afterwards could
tell the two apart.

The candidate list is here for the same reason it is in the agent's prompt: to
be looked at. Acting on one is the agent's move to make.
"""
from fastapi import APIRouter

from backend.database import db
from backend.api.schemas import CandidateOut
from backend.services import candidates

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[str])
def list_watchlist():
    return db.get_watchlist()


@router.get("/candidates", response_model=list[CandidateOut])
def get_candidates():
    """The screened names the agent may commission, minus the ones it already
    tracks. The same list ``agent.build_prompt`` puts in front of the model."""
    return [CandidateOut.model_validate(c) for c in candidates.fetch_candidates()]
