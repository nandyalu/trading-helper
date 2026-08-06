"""Weekly digest, on demand — reuses bot.digest.gather_digest() directly,
already a pure, DB-only function returning a plain dataclass."""
from fastapi import APIRouter

from bot.api.schemas import DigestOut
from bot.digest import gather_digest

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("", response_model=DigestOut)
def get_digest():
    return DigestOut.model_validate(gather_digest())
