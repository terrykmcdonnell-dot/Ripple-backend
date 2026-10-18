"""
RevenueCat → Supabase sync.

Webhook endpoint (FastAPI): POST {your API origin}/revenuecat

Configure in `.env`:
  REVENUECAT_WEBHOOK_PUBLIC_URL — full URL to paste into RevenueCat (informational / startup log)
  REVENUECAT_WEBHOOK_AUTHORIZATION — optional; must match RevenueCat dashboard header exactly
  REVENUECAT_ENTITLEMENT_ID — entitlement id (default pro)

public.users is matched by Supabase Auth id (`users.auth_user_id` = RevenueCat `app_user_id`
after logIn). Email is only a fallback for rows created before that column existed.
A missing row is inserted. Anonymous RevenueCat ids are ignored.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from app.supabase_db import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["revenuecat"])

ACTIVE_PURCHASE_TYPES = frozenset(
    {
        "INITIAL_PURCHASE",
        "RENEWAL",
        "UNCANCELLATION",
        "PRODUCT_CHANGE",
        "NON_RENEWING_PURCHASE",
        "SUBSCRIPTION_EXTENDED",
        "TEMPORARY_ENTITLEMENT_GRANT",
    }
)


def _extract_event(payload: dict[str, Any]) -> dict[str, Any]:
    ev = payload.get("event")
    if isinstance(ev, dict):
        return ev
    return payload


def _has_pro_entitlement(event: dict[str, Any], pro_id: str) -> bool:
    ids = event.get("entitlement_ids")
    if isinstance(ids, list) and pro_id in ids:
        return True
    eid = event.get("entitlement_id")
    return eid == pro_id


def _derive_plan(product_id: str | None, period_type: str | None) -> str:
    if period_type == "TRIAL":
        return "trial"
    if period_type == "INTRO":
        return "intro"
    if not product_id:
        return "unknown"
    pid = product_id.lower()
    if any(x in pid for x in ("lifetime", "forever", "one_time", "onetime")):
        return "lifetime"
    if "month" in pid:
        return "monthly"
    if any(x in pid for x in ("annual", "year", "yearly", "_yr")):
        return "annual"
    return "unknown"


def _compute_rc_fields(event: dict[str, Any], pro_entitlement: str) -> tuple[str, str, str] | None:
    """
    Returns (rc_customer_id, rc_subscription_status, rc_subscription_plan) or None to skip DB write.
    """
    etype = str(event.get("type") or "")
    if etype == "TEST":
        return None

    customer_id = str(event.get("original_app_user_id") or event.get("app_user_id") or "").strip()
    product_id = event.get("product_id")
    if isinstance(product_id, str):
        product_id = product_id.strip() or None
    else:
        product_id = None

    period_type = event.get("period_type")
    if isinstance(period_type, str):
        period_type = period_type.strip().upper()
    else:
        period_type = None

    exp_ms = event.get("expiration_at_ms")
    now_ms = int(time.time() * 1000)

    plan = _derive_plan(product_id, period_type)
    has_pro = _has_pro_entitlement(event, pro_entitlement)
    expiry_future = exp_ms is None or (isinstance(exp_ms, int) and exp_ms > now_ms)

    if etype == "EXPIRATION":
        status = "expired"
        if not customer_id:
            return None
        return customer_id, status, plan

    if etype in ("REFUND",):
        if not customer_id:
            return None
        return customer_id, "expired", plan

    if etype == "BILLING_ISSUE":
        if not customer_id:
            return None
        return customer_id, "billing_issue", plan

    if etype == "CANCELLATION":
        if not customer_id:
            return None
        # Still entitled until expiration when expiry is in the future.
        if has_pro and expiry_future:
            return customer_id, "active", plan
        return customer_id, "expired" if isinstance(exp_ms, int) and exp_ms <= now_ms else "inactive", plan

    if etype == "SUBSCRIPTION_PAUSED":
        if not customer_id:
            return None
        return customer_id, "active", plan

    if etype in ACTIVE_PURCHASE_TYPES:
        if not customer_id:
            return None
        if not expiry_future:
            return customer_id, "expired", plan
        entitled = has_pro or etype == "TEMPORARY_ENTITLEMENT_GRANT"
        if (
            not entitled
            and etype
            in (
                "INITIAL_PURCHASE",
                "RENEWAL",
                "UNCANCELLATION",
                "PRODUCT_CHANGE",
                "NON_RENEWING_PURCHASE",
            )
            and product_id
        ):
            entitled = True
        status = "active" if entitled else "inactive"
        return customer_id, status, plan

    if not customer_id:
        return None
    return customer_id, "inactive", plan


_AUTH_USER_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_supabase_auth_id(app_user_id: str) -> bool:
    """RevenueCat anonymous ids (`$RCAnonymousID:…`) are not Supabase users."""
    return _AUTH_USER_ID_RE.fullmatch(app_user_id.strip()) is not None


async def _auth_profile_for_app_user_id(
    sb_url: str, service_key: str, app_user_id: str
) -> dict[str, str] | None:
    """Auth admin user for a Supabase id. Email may be empty."""
    uid = app_user_id.strip()
    if not _is_supabase_auth_id(uid):
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
    meta = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    name = ""
    for key in ("full_name", "name"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            name = raw.strip()
            break
    if not name and email and "@" in email:
        name = email.split("@", 1)[0]
    return {"id": uid, "email": email, "name": name or "User"}


def _target_app_user_ids(event: dict[str, Any]) -> list[str]:
    uid = event.get("app_user_id") or event.get("original_app_user_id")
    if uid:
        return [str(uid).strip()]
    return []


def _transfer_destination_ids(event: dict[str, Any]) -> list[str]:
    raw = event.get("transferred_to") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _rc_payload(rc_customer_id: str, status: str, plan: str) -> dict[str, str]:
    return {
        "rc_customer_id": rc_customer_id,
        "rc_subscription_status": status,
        "rc_subscription_plan": plan,
    }


def _row_id(result: Any) -> int | None:
    data = getattr(result, "data", None)
    if isinstance(data, dict) and data.get("id") is not None:
        return int(data["id"])
    return None


async def _upsert_subscription_for_auth_user(
    sb_url: str,
    service_key: str,
    auth_user_id: str,
    rc_customer_id: str,
    status: str,
    plan: str,
) -> bool:
    """
    Write RevenueCat columns onto public.users for this Supabase Auth id.
    Creates the row when missing. Existing rows that predate auth_user_id are
    linked by email once, then updated by id.
    """
    uid = auth_user_id.strip()
    if not _is_supabase_auth_id(uid):
        logger.info("RevenueCat webhook: skip non-auth app_user_id=%s", uid)
        return False

    sb = get_supabase()
    payload = _rc_payload(rc_customer_id, status, plan)
    by_auth = sb.table("users").select("id").eq("auth_user_id", uid).maybe_single().execute()
    row_id = _row_id(by_auth)
    if row_id is not None:
        sb.table("users").update(payload).eq("id", row_id).execute()
        return True

    profile = await _auth_profile_for_app_user_id(sb_url, service_key, uid)
    email = (profile or {}).get("email") or ""
    if email:
        by_email = sb.table("users").select("id").eq("email", email).maybe_single().execute()
        row_id = _row_id(by_email)
        if row_id is not None:
            sb.table("users").update({**payload, "auth_user_id": uid}).eq("id", row_id).execute()
            return True

    insert_row: dict[str, Any] = {
        "auth_user_id": uid,
        "name": (profile or {}).get("name") or "User",
        "password": "",
        **payload,
    }
    if email:
        insert_row["email"] = email
    sb.table("users").insert(insert_row).execute()
    return True


@router.post("/revenuecat")
async def revenuecat_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()

    expected = (settings.REVENUECAT_WEBHOOK_AUTHORIZATION or "").strip()
    if expected:
        incoming = (authorization or "").strip()
        if incoming != expected:
            raise HTTPException(status_code=401, detail="Invalid authorization")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = _extract_event(payload if isinstance(payload, dict) else {})
    pro_id = settings.REVENUECAT_ENTITLEMENT_ID.strip()

    etype = str(event.get("type") or "")
    if etype == "TRANSFER":
        sb_url = settings.SUPABASE_URL
        sb_key = settings.SUPABASE_SECRET_KEY
        rc_customer_id = str(event.get("original_app_user_id") or "").strip()
        for uid in _transfer_destination_ids(event):
            try:
                await _upsert_subscription_for_auth_user(
                    sb_url, sb_key, uid, rc_customer_id or uid, "active", "unknown"
                )
            except Exception as exc:
                logger.exception("TRANSFER failed for app_user_id=%s: %s", uid, exc)
        return {"status": "ok"}

    computed = _compute_rc_fields(event, pro_id)
    if computed is None:
        return {"status": "ok"}

    rc_customer_id, rc_status, rc_plan = computed

    app_users = _target_app_user_ids(event)
    if not app_users:
        logger.info("RevenueCat webhook: no app_user_id on event type=%s", event.get("type"))
        return {"status": "ok"}

    sb_url = settings.SUPABASE_URL
    sb_key = settings.SUPABASE_SECRET_KEY

    updated = 0
    for uid in app_users:
        try:
            if await _upsert_subscription_for_auth_user(
                sb_url, sb_key, uid, rc_customer_id, rc_status, rc_plan
            ):
                updated += 1
        except Exception as exc:
            logger.exception("Failed updating users row for app_user_id=%s: %s", uid, exc)

    logger.info(
        "RevenueCat webhook processed type=%s updated_rows=%s status=%s plan=%s",
        event.get("type"),
        updated,
        rc_status,
        rc_plan,
    )
    return {"status": "ok"}
