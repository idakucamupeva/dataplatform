"""Shared FastAPI dependencies: current user, authorisation helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import DataProduct, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        raise credentials_error
    user = db.execute(select(User).where(User.username == payload["sub"])).scalars().first()
    if user is None:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrator role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_data_product(dp_id: int, db: DbSession) -> DataProduct:
    dp = db.get(DataProduct, dp_id)
    if dp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Data product not found")
    return dp


TargetDataProduct = Annotated[DataProduct, Depends(get_data_product)]


def assert_can_edit(dp: DataProduct, user: User) -> None:
    """Producers edit their own products; admins may edit anything."""
    if dp.owner_id != user.id and not user.is_admin():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the owner of this data product (or a platform administrator) may change it",
        )


def assert_can_govern(user: User) -> None:
    if not user.can_govern():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Governance role required")
