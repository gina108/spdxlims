from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.models import AuditEvent


def log_audit(
    db: Session,
    *,
    actor_user_id: UUID | None,
    entity: str,
    entity_id: str,
    action: str,
    before_json: dict[str, Any] | None = None,
    after_json: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            entity=entity,
            entity_id=entity_id,
            action=action,
            before_json=before_json,
            after_json=after_json,
        )
    )
