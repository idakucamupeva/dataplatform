from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.serializers import user_out
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Role, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._-]+$")
    email: EmailStr
    full_name: str = Field(default="", alias="fullName")
    password: str = Field(min_length=8)

    model_config = {"populate_by_name": True}


def _token_response(user: User) -> dict:
    return {
        "accessToken": create_access_token(user.username, {"role": str(user.role)}),
        "tokenType": "bearer",
        "user": user_out(user),
    }


@router.post("/login")
def login(payload: LoginRequest, db: DbSession) -> dict:
    user = db.execute(select(User).where(User.username == payload.username)).scalars().first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return _token_response(user)


@router.post("/token")
def login_form(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> dict:
    """OAuth2 password flow, so the generated API docs can authenticate too."""
    user = db.execute(select(User).where(User.username == form.username)).scalars().first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    response = _token_response(user)
    return {**response, "access_token": response["accessToken"], "token_type": "bearer"}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> dict:
    exists = db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).scalars().first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username or e-mail is already taken")
    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name or payload.username.title(),
        hashed_password=hash_password(payload.password),
        role=Role.USER,
    )
    db.add(user)
    db.flush()
    return _token_response(user)


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return user_out(user)


@router.get("/users")
def list_users(db: DbSession, _: CurrentUser) -> list[dict]:
    return [user_out(u) for u in db.execute(select(User).order_by(User.username)).scalars()]
