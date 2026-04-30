from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.schemas.alarm_history import AlarmHistoryResponse, AlarmHistoryUpsert
from app.supabase_db import get_supabase

router = APIRouter(prefix="/api/alarm-history", tags=["alarm-history"])

HISTORY_TABLE = "alarm_history"
ALARMS_TABLE = "alarms"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts_key(dt: datetime) -> str:
    """RFC3339 UTC suitable for timestamptz equality filters."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _assert_alarm_owned(supabase: Client, alarm_id: int, user_id: int) -> dict[str, Any]:
    try:
        result = (
            supabase.table(ALARMS_TABLE)
            .select("id,user_id")
            .eq("id", alarm_id)
            .maybe_single()
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    if result is None or not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found")
    row = result.data
    assert isinstance(row, dict)
    if int(row["user_id"]) != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alarm does not belong to this user")
    return row


def _row_to_response(row: dict[str, Any]) -> AlarmHistoryResponse:
    return AlarmHistoryResponse.model_validate(row)


@router.get("/", response_model=list[AlarmHistoryResponse])
def list_alarm_history(
    user_id: int = Query(..., description="public.users.id"),
    limit: int = Query(500, ge=1, le=2000),
    supabase: Client = Depends(get_supabase),
) -> list[AlarmHistoryResponse]:
    try:
        result = (
            supabase.table(HISTORY_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("scheduled_fire_at", desc=True)
            .limit(limit)
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    rows = result.data or []
    return [_row_to_response(r) for r in rows]


@router.post("/", response_model=AlarmHistoryResponse)
def upsert_alarm_history(
    payload: AlarmHistoryUpsert,
    supabase: Client = Depends(get_supabase),
) -> AlarmHistoryResponse:
    _assert_alarm_owned(supabase, payload.alarm_id, payload.user_id)

    fire_key = _ts_key(payload.scheduled_fire_at)

    try:
        existing_result = (
            supabase.table(HISTORY_TABLE)
            .select("*")
            .eq("user_id", payload.user_id)
            .eq("alarm_id", payload.alarm_id)
            .eq("scheduled_fire_at", fire_key)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    rows_existing = existing_result.data or []
    existing = rows_existing[0] if rows_existing else None

    action_at = payload.action_at
    if payload.status in ("dismissed", "snoozed"):
        action_at = action_at or _utc_now()
    elif payload.status == "missed":
        action_at = None

    snooze_minutes = payload.snooze_minutes if payload.status == "snoozed" else None

    insert_body: dict[str, Any] = {
        "user_id": payload.user_id,
        "alarm_id": payload.alarm_id,
        "label": payload.label.strip(),
        "category": payload.category.strip(),
        "scheduled_fire_at": fire_key,
        "status": payload.status,
        "action_at": _ts_key(action_at) if action_at else None,
        "snooze_minutes": snooze_minutes,
        "updated_at": _ts_key(_utc_now()),
    }

    if existing:
        assert isinstance(existing, dict)
        prev_status = str(existing["status"])
        if payload.status == "missed" and prev_status in ("dismissed", "snoozed"):
            return _row_to_response(existing)
        if payload.status == "missed" and prev_status == "missed":
            return _row_to_response(existing)

        patch = {
            "status": payload.status,
            "label": insert_body["label"] or existing.get("label") or "",
            "category": insert_body["category"] or existing.get("category") or "",
            "action_at": insert_body["action_at"],
            "snooze_minutes": snooze_minutes,
            "updated_at": insert_body["updated_at"],
        }
        try:
            updated = (
                supabase.table(HISTORY_TABLE)
                .update(patch)
                .eq("id", int(existing["id"]))
                .execute()
            )
        except APIError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
        rows = updated.data or []
        if not rows:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Update returned no row")
        return _row_to_response(rows[0])

    insert_body["created_at"] = insert_body["updated_at"]
    try:
        inserted = supabase.table(HISTORY_TABLE).insert(insert_body).execute()
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    rows = inserted.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Insert returned no row")
    return _row_to_response(rows[0])
