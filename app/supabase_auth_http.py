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


async def fetch_auth_user_email_from_access_token(
    sb_url: str,
    api_key: str,
    access_token: str,
) -> str | None:
    """Resolve email via GET /auth/v1/user with the user's access_token."""
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
    data = r.json()
    if isinstance(data, dict) and isinstance(data.get("email"), str):
        email = (data["email"] or "").strip().lower()
        return email or None
    user = data.get("user") if isinstance(data.get("user"), dict) else None
    if isinstance(user, dict):
        email = (user.get("email") or "").strip().lower()
        return email or None
    return None
