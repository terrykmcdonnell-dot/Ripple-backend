"""
RevenueCat → Supabase sync.

Webhook endpoint (FastAPI): POST {your API origin}/revenuecat

Configure in `.env`:
  REVENUECAT_WEBHOOK_PUBLIC_URL — full URL to paste into RevenueCat (informational / startup log)
  REVENUECAT_WEBHOOK_AUTHORIZATION — optional; must match RevenueCat dashboard header exactly
  REVENUECAT_ENTITLEMENT_ID — entitlement id (default pro)

public.users is matched via Supabase Auth admin lookup: event app_user_id → auth user → email → users.email.
"""

from __future__ import annotations

import logging
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


async def _auth_email_for_app_user_id(sb_url: str, service_key: str, app_user_id: str) -> str | None:
    """Resolve Supabase Auth user email from RevenueCat app_user_id (Supabase Auth UUID)."""
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


async def _apply_update(email: str, rc_customer_id: str, status: str, plan: str) -> None:
    sb = get_supabase()
    payload = {
        "rc_customer_id": rc_customer_id,
        "rc_subscription_status": status,
        "rc_subscription_plan": plan,
    }
    sb.table("users").update(payload).eq("email", email).execute()


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
            email = await _auth_email_for_app_user_id(sb_url, sb_key, uid)
            if not email:
                logger.warning("TRANSFER: no email for app_user_id=%s", uid)
                continue
            await _apply_update(email, rc_customer_id or uid, "active", "unknown")
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
        email = await _auth_email_for_app_user_id(sb_url, sb_key, uid)
        if not email:
            logger.warning("No email for RevenueCat app_user_id=%s (event=%s)", uid, event.get("type"))
            continue
        try:
            await _apply_update(email, rc_customer_id, rc_status, rc_plan)
            updated += 1
        except Exception as exc:
            logger.exception("Failed updating users row for %s: %s", email, exc)

    logger.info(
        "RevenueCat webhook processed type=%s updated_rows=%s status=%s plan=%s",
        event.get("type"),
        updated,
        rc_status,
        rc_plan,
    )
    return {"status": "ok"}
