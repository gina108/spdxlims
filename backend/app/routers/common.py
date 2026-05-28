from uuid import UUID

from fastapi import Depends

from app.core.deps import get_current_user
from app.models.models import AppUser


def actor_from_header(current_user: AppUser = Depends(get_current_user)) -> UUID:
    return current_user.id
