from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.models import AppUser, TestCatalog


def ensure_user(db, email: str, full_name: str, role: str, password: str) -> None:
    existing = db.scalars(select(AppUser).where(AppUser.email == email)).first()
    if existing:
        return
    db.add(
        AppUser(
            email=email,
            full_name=full_name,
            role=role,
            password_hash=hash_password(password),
            is_active=True,
        )
    )


def ensure_test(db, code: str, name: str, specimen_type: str, unit: str) -> None:
    existing = db.scalars(select(TestCatalog).where(TestCatalog.code == code)).first()
    if existing:
        return
    db.add(TestCatalog(code=code, name=name, specimen_type=specimen_type, unit=unit, method="manual", active=True))


def main() -> None:
    db = SessionLocal()
    try:
        admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@spdxlims.local")
        admin_password = os.getenv("SEED_ADMIN_PASSWORD", "")
        manager_password = os.getenv("SEED_MANAGER_PASSWORD", "")
        tech_password = os.getenv("SEED_TECH_PASSWORD", "")
        app_env = os.getenv("APP_ENV", "dev").lower()

        if app_env in {"prod", "production"} and not admin_password:
            raise RuntimeError("SEED_ADMIN_PASSWORD is required when APP_ENV is production.")

        ensure_user(db, admin_email, "System Admin", "admin", admin_password or "Admin#12345")
        if manager_password:
            ensure_user(db, os.getenv("SEED_MANAGER_EMAIL", "manager@spdxlims.local"), "Lab Manager", "lab_manager", manager_password)
        elif app_env not in {"prod", "production"}:
            ensure_user(db, "manager@spdxlims.local", "Lab Manager", "lab_manager", "Manager#12345")
        if tech_password:
            ensure_user(db, os.getenv("SEED_TECH_EMAIL", "tech@spdxlims.local"), "Lab Tech", "tech", tech_password)
        elif app_env not in {"prod", "production"}:
            ensure_user(db, "tech@spdxlims.local", "Lab Tech", "tech", "Tech#12345")

        ensure_test(db, "CBC", "Complete Blood Count", "blood", "x10^3/uL")
        ensure_test(db, "GLU", "Glucose", "serum", "mg/dL")

        db.commit()
        print("Seed completed.")
        print(f"Admin login: {admin_email} / {'configured password' if admin_password else 'Admin#12345'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
