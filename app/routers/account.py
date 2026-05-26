from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.config import get_settings
from app.supabase_auth_http import delete_auth_admin_user, fetch_auth_user_from_access_token
from app.supabase_db import get_supabase

router = APIRouter(prefix="/api/account", tags=["account"])

logger = logging.getLogger(__name__)

USERS_TABLE = "users"
ALARMS_TABLE = "alarms"
ALARM_HISTORY_TABLE = "alarm_history"


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization must be Bearer token")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return token


def _delete_user_data(supabase: Client, user_id: int) -> None:
    try:
        supabase.table(ALARMS_TABLE).delete().eq("user_id", user_id).execute()
        supabase.table(ALARM_HISTORY_TABLE).delete().eq("user_id", user_id).execute()
        supabase.table(USERS_TABLE).delete().eq("id", user_id).execute()
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e


async def _close_account_for_token(access_token: str, supabase: Client) -> None:
    settings = get_settings()
    auth_user = await fetch_auth_user_from_access_token(
        settings.SUPABASE_URL,
        settings.SUPABASE_SECRET_KEY,
        access_token,
    )
    if not auth_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    email = auth_user["email"]
    auth_user_id = auth_user["id"]

    try:
        result = supabase.table(USERS_TABLE).select("id").eq("email", email).maybe_single().execute()
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    row = result.data if result is not None else None
    if isinstance(row, dict) and row.get("id") is not None:
        _delete_user_data(supabase, int(row["id"]))

    deleted = await delete_auth_admin_user(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY, auth_user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not remove auth account",
        )


@router.post("/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_account(
    authorization: str | None = Header(None),
    supabase: Client = Depends(get_supabase),
) -> None:
    """Permanently delete the signed-in user's alarms, history, profile row, and Supabase Auth account."""
    token = _extract_bearer_token(authorization)
    await _close_account_for_token(token, supabase)
