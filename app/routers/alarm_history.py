from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.schemas.alarm_history import AlarmHistoryResponse, AlarmHistoryUpsert
from app.supabase_db import get_supabase

logger = logging.getLogger(__name__)

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


def _postgrest_detail(exc: APIError) -> str:
    parts = [p for p in (exc.message, exc.details, exc.hint, str(exc.code) if exc.code else None) if p]
    return " | ".join(parts) if parts else repr(exc)


def _is_unique_violation(exc: APIError) -> bool:
    blob = " ".join(filter(None, [exc.message, exc.details, str(exc.code)])).lower()
    return "23505" in blob or "duplicate key" in blob or "unique constraint" in blob


def _is_missing_history_table(exc: APIError) -> bool:
    blob = " ".join(filter(None, [exc.message, exc.details, str(exc.code)])).lower()
    return "alarm_history" in blob and (
        "does not exist" in blob or "schema cache" in blob or "pgrst205" in blob or "42p01" in blob
    )


def _is_fk_violation(exc: APIError) -> bool:
    blob = " ".join(filter(None, [exc.message, exc.details, str(exc.code)])).lower()
    return "23503" in blob or "foreign key" in blob


def _raise_from_api_error(exc: APIError, *, context: str) -> None:
    """Logs PostgREST errors clearly (502 bodies are often not visible in reverse-proxy logs)."""
    detail = _postgrest_detail(exc)
    logger.warning("%s: %s", context, detail)

    if _is_missing_history_table(exc):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Database schema is missing `alarm_history` (or PostgREST cannot see it). "
                "Apply `supabase/migrations/20260430120000_alarm_history.sql` to your Supabase project. "
                f"Raw error: {detail}"
            ),
        ) from exc
    if _is_fk_violation(exc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "alarm_history insert/update violates a foreign key "
                "(check `user_id` exists in `users` and `alarm_id` exists in `alarms`). "
                f"Raw error: {detail}"
            ),
        ) from exc

    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc


def _fetch_history_row(
    supabase: Client,
    *,
    user_id: int,
    alarm_id: int,
    fire_key: str,
) -> dict[str, Any] | None:
    result = (
        supabase.table(HISTORY_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .eq("alarm_id", alarm_id)
        .eq("scheduled_fire_at", fire_key)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _assert_alarm_owned(supabase: Client, alarm_id: int, user_id: int) -> dict[str, Any]:
    try:
        result = (
            supabase.table(ALARMS_TABLE)
            .select("id,user_id")
            .eq("id", alarm_id)
            .limit(1)
            .execute()
        )
    except APIError as e:
        _raise_from_api_error(e, context="alarm_history: alarms lookup")

    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found")
    row = rows[0]
    assert isinstance(row, dict)
    if int(row["user_id"]) != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alarm does not belong to this user")
    return row


def _row_to_response(row: dict[str, Any]) -> AlarmHistoryResponse:
    return AlarmHistoryResponse.model_validate(row)


def _run_history_update(
    supabase: Client,
    *,
    row_id: int,
    patch: dict[str, Any],
    fire_key: str,
    user_id: int,
    alarm_id: int,
) -> AlarmHistoryResponse:
    try:
        updated = (
            supabase.table(HISTORY_TABLE)
            .update(patch)
            .eq("id", row_id)
            .execute()
        )
    except APIError as e:
        _raise_from_api_error(e, context="alarm_history: update")

    out_rows = updated.data or []
    if out_rows:
        return _row_to_response(out_rows[0])

    refetched_upd: dict[str, Any] | None = None
    try:
        refetched_upd = _fetch_history_row(supabase, user_id=user_id, alarm_id=alarm_id, fire_key=fire_key)
    except APIError as e:
        _raise_from_api_error(e, context="alarm_history: refetch after empty update")

    if refetched_upd:
        return _row_to_response(refetched_upd)

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Update succeeded but PostgREST returned no row body; refetch also empty.",
    )


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
        _raise_from_api_error(e, context="alarm_history: list")
    rows = result.data or []
    return [_row_to_response(r) for r in rows]


def _merge_and_respond(
    supabase: Client,
    payload: AlarmHistoryUpsert,
    existing: dict[str, Any],
    insert_body: dict[str, Any],
    snooze_minutes: int | None,
    fire_key: str,
) -> AlarmHistoryResponse:
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
    return _run_history_update(
        supabase,
        row_id=int(existing["id"]),
        patch=patch,
        fire_key=fire_key,
        user_id=payload.user_id,
        alarm_id=payload.alarm_id,
    )


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
        _raise_from_api_error(e, context="alarm_history: select existing")

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
        return _merge_and_respond(supabase, payload, existing, insert_body, snooze_minutes, fire_key)

    insert_body["created_at"] = insert_body["updated_at"]
    try:
        inserted = supabase.table(HISTORY_TABLE).insert(insert_body).execute()
    except APIError as e:
        if _is_unique_violation(e):
            logger.info(
                "alarm_history: insert duplicate for user=%s alarm=%s fire=%s — retrying as merge",
                payload.user_id,
                payload.alarm_id,
                fire_key,
            )
            try:
                concurrent = _fetch_history_row(
                    supabase,
                    user_id=payload.user_id,
                    alarm_id=payload.alarm_id,
                    fire_key=fire_key,
                )
            except APIError as e2:
                _raise_from_api_error(e2, context="alarm_history: refetch after duplicate insert")
            if concurrent:
                return _merge_and_respond(supabase, payload, concurrent, insert_body, snooze_minutes, fire_key)
        _raise_from_api_error(e, context="alarm_history: insert")

    ins_rows = inserted.data or []
    if ins_rows:
        return _row_to_response(ins_rows[0])

    refetched_after_insert: dict[str, Any] | None = None
    try:
        refetched_after_insert = _fetch_history_row(
            supabase,
            user_id=payload.user_id,
            alarm_id=payload.alarm_id,
            fire_key=fire_key,
        )
    except APIError as e:
        _raise_from_api_error(e, context="alarm_history: refetch after empty insert body")

    if refetched_after_insert:
        return _row_to_response(refetched_after_insert)

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Insert reported success but returned no row; apply migrations or check PostgREST `Prefer: return=representation`.",
    )
