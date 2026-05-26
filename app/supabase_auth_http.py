"""Supabase Auth REST helpers (JWT user lookup + admin user lookup)."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_auth_admin_user_email_by_id(sb_url: str, service_key: str, app_user_id: str) -> str | None:
    """Resolve email via GET /auth/v1/admin/users/{uuid} (service role)."""
    uid = app_user_id.strip()
    if not uid:
        return None
    url = f"{sb_url.rstrip('/')}/auth/v1/admin/users/{uid}"
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers)
    if r.status_code != 200:
        logger.warning("Auth admin lookup failed %s for uid=%s: %s", r.status_code, uid, r.text[:500])
        return None
    data = r.json()
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    if not isinstance(user, dict):
        return None
    email = (user.get("email") or "").strip().lower()
    return email or None


def _parse_auth_user_payload(data: object) -> dict[str, str] | None:
    user = data if isinstance(data, dict) else None
    if user is None:
        return None
    nested = user.get("user") if isinstance(user.get("user"), dict) else None
    if nested is not None:
        user = nested
    uid = (user.get("id") or "").strip()
    email = (user.get("email") or "").strip().lower()
    if not uid or not email:
        return None
    return {"id": uid, "email": email}


async def fetch_auth_user_from_access_token(
    sb_url: str,
    api_key: str,
    access_token: str,
) -> dict[str, str] | None:
    """Resolve `{id, email}` via GET /auth/v1/user with the user's access_token."""
    token = access_token.strip()
    if not token:
        return None
    url = f"{sb_url.rstrip('/')}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": api_key,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers)
    if r.status_code != 200:
        logger.warning("auth/v1/user failed %s: %s", r.status_code, r.text[:400])
        return None
    return _parse_auth_user_payload(r.json())


async def fetch_auth_user_email_from_access_token(
    sb_url: str,
    api_key: str,
    access_token: str,
) -> str | None:
    """Resolve email via GET /auth/v1/user with the user's access_token."""
    user = await fetch_auth_user_from_access_token(sb_url, api_key, access_token)
    return user["email"] if user else None


async def delete_auth_admin_user(sb_url: str, service_key: str, auth_user_id: str) -> bool:
    """Delete Supabase Auth user via service role (DELETE /auth/v1/admin/users/{id})."""
    uid = auth_user_id.strip()
    if not uid:
        return False
    url = f"{sb_url.rstrip('/')}/auth/v1/admin/users/{uid}"
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.delete(url, headers=headers)
    if r.status_code in (200, 204):
        return True
    logger.warning("Auth admin delete failed %s for uid=%s: %s", r.status_code, uid, r.text[:500])
    return False
