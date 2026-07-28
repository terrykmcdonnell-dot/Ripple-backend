from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.supabase_auth_http import AuthAdminUserCreateError, create_auth_admin_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SignUpRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=1, max_length=120)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def sign_up(body: SignUpRequest) -> dict[str, str]:
    """
    Create a confirmed Supabase Auth user when client-side signUp cannot send confirmation email.
    The mobile app signs in with password immediately after this succeeds.
    """
    email = body.email.strip().lower()
    name = body.name.strip()

    if not _EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Enter a valid email address.")
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name is required.")

    settings = get_settings()
    try:
        await create_auth_admin_user(
            settings.SUPABASE_URL,
            settings.SUPABASE_SECRET_KEY,
            email=email,
            password=body.password,
            name=name,
        )
    except AuthAdminUserCreateError as exc:
        if exc.status_code == 422 and (exc.error_code or "").lower() in {"email_exists", "user_already_exists"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already registered. Sign in or use a different email.",
            ) from exc
        logger.warning("Auth admin signup failed %s (%s): %s", exc.status_code, exc.error_code, exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not create account right now. Try again in a moment.",
        ) from exc

    return {"status": "created"}
