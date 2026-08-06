"""Weekly digest, on demand — reuses backend.services.digest.gather_digest() directly,
already a pure, DB-only function returning a plain dataclass."""
from fastapi import APIRouter

from backend.api.schemas import DigestOut
from backend.services.digest import gather_digest

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("", response_model=DigestOut)
def get_digest():
    return DigestOut.model_validate(gather_digest())
