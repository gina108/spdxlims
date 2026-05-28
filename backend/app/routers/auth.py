from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.models import AppUser

router = APIRouter()


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalars(select(AppUser).where(AppUser.email == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    token = create_access_token(str(user.id), extra={"role": user.role, "email": user.email})
    return LoginResponse(access_token=token, user_id=str(user.id), email=user.email, role=user.role)


@router.get("/me")
def me(current_user: AppUser = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "is_active": current_user.is_active,
    }
