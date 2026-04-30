from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.schemas.alarm import AlarmCreate, AlarmResponse, AlarmToggle, AlarmUpdate
from app.supabase_db import get_supabase

router = APIRouter(prefix="/api/alarm", tags=["alarm"])

ALARMS_TABLE = "alarms"
CATEGORY_TABLE = "category"


def _resolve_category_id(supabase: Client, name: str) -> int:
    try:
        result = (
            supabase.table(CATEGORY_TABLE)
            .select("id")
            .eq("name", name)
            .maybe_single()
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Category "{name}" not found',
        )
    row = result.data
    assert isinstance(row, dict)
    return int(row["id"])


def _category_names_by_ids(supabase: Client, ids: list[int]) -> dict[int, str]:
    """Load category names keyed by category id."""
    if not ids:
        return {}
    unique_ids = list(dict.fromkeys(ids))
    try:
        result = (
            supabase.table(CATEGORY_TABLE)
            .select("id,name")
            .in_("id", unique_ids)
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    mapping: dict[int, str] = {}
    for row in result.data or []:
        mapping[int(row["id"])] = str(row["name"])
    return mapping


def _alarm_rows_to_responses(supabase: Client, rows: list[dict[str, Any]]) -> list[AlarmResponse]:
    if not rows:
        return []
    cat_ids = [int(r["category"]) for r in rows]
    names = _category_names_by_ids(supabase, cat_ids)
    out: list[AlarmResponse] = []
    for row in rows:
        cid = int(row["category"])
        name = names.get(cid)
        if name is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Category id {cid} has no row in the category table",
            )
        out.append(AlarmResponse.model_validate({**row, "category": name}))
    return out


def _run_alarm_update(supabase: Client, alarm_id: int, patch: dict[str, Any]) -> AlarmResponse:
    try:
        result = (
            supabase.table(ALARMS_TABLE)
            .update(patch)
            .eq("id", alarm_id)
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    rows = result.data or []
    if rows:
        return _alarm_rows_to_responses(supabase, [rows[0]])[0]
    existing = (
        supabase.table(ALARMS_TABLE)
        .select("*")
        .eq("id", alarm_id)
        .maybe_single()
        .execute()
    )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found")
    return _alarm_rows_to_responses(supabase, [existing.data])[0]


@router.get("/", response_model=list[AlarmResponse])
def list_alarms(
    user_id: int = Query(..., description="Return alarms only for this user"),
    supabase: Client = Depends(get_supabase),
) -> list[AlarmResponse]:
    try:
        result = (
            supabase.table(ALARMS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("scheduled_at")
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    rows = result.data or []
    return _alarm_rows_to_responses(supabase, rows)


@router.get("/{alarm_id}", response_model=AlarmResponse)
def get_alarm(alarm_id: int, supabase: Client = Depends(get_supabase)) -> AlarmResponse:
    try:
        result = (
            supabase.table(ALARMS_TABLE)
            .select("*")
            .eq("id", alarm_id)
            .maybe_single()
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found")
    return _alarm_rows_to_responses(supabase, [result.data])[0]


@router.post("/", response_model=AlarmResponse, status_code=status.HTTP_201_CREATED)
def create_alarm(payload: AlarmCreate, supabase: Client = Depends(get_supabase)) -> AlarmResponse:
    category_id = _resolve_category_id(supabase, payload.category)
    insert_payload = payload.model_dump(mode="json", exclude={"category"})
    insert_payload["category"] = category_id
    try:
        result = supabase.table(ALARMS_TABLE).insert(insert_payload).execute()
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    rows = result.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Insert succeeded but returned no row",
        )
    return _alarm_rows_to_responses(supabase, [rows[0]])[0]


@router.patch("/{alarm_id}/toggle", response_model=AlarmResponse)
def toggle_alarm(
    alarm_id: int,
    payload: AlarmToggle,
    supabase: Client = Depends(get_supabase),
) -> AlarmResponse:
    """Set `is_enabled` for one alarm by id."""
    return _run_alarm_update(supabase, alarm_id, {"is_enabled": payload.is_enabled})


@router.patch("/{alarm_id}", response_model=AlarmResponse)
def update_alarm(
    alarm_id: int,
    payload: AlarmUpdate,
    supabase: Client = Depends(get_supabase),
) -> AlarmResponse:
    patch = payload.model_dump(mode="json", exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    if "category" in patch:
        category_name = patch.pop("category")
        if not isinstance(category_name, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="category must be a category name string",
            )
        patch["category"] = _resolve_category_id(supabase, category_name)
    return _run_alarm_update(supabase, alarm_id, patch)


@router.delete("/{alarm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alarm(alarm_id: int, supabase: Client = Depends(get_supabase)) -> None:
    try:
        existing = (
            supabase.table(ALARMS_TABLE)
            .select("id")
            .eq("id", alarm_id)
            .maybe_single()
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found")
    try:
        supabase.table(ALARMS_TABLE).delete().eq("id", alarm_id).execute()
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
