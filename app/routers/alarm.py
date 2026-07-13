from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.schemas.alarm import AlarmCreate, AlarmResponse, AlarmToggle, AlarmUpdate
from app.routers.alarm_history import delete_history_for_alarm
from app.supabase_db import get_supabase

router = APIRouter(prefix="/api/alarm", tags=["alarm"])

ALARMS_TABLE = "alarms"
CATEGORY_TABLE = "category"


def _resolve_category_id_by_name(supabase: Client, user_id: int, name: str) -> int:
    clean = name.strip()
    if not clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="category is required")
    try:
        result = (
            supabase.table(CATEGORY_TABLE)
            .select("id")
            .or_(f"user_id.is.null,user_id.eq.{user_id}")
            .eq("is_archived", False)
            .ilike("name", clean)
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    rows = result.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Category "{clean}" not found',
        )
    # Prefer a user's category over a system category when names overlap.
    rows.sort(key=lambda r: 0 if r.get("user_id") is not None else 1)
    return int(rows[0]["id"])


def _resolve_category_id(supabase: Client, user_id: int, category_id: int | None, category_name: str | None) -> int:
    if category_id is not None:
        try:
            result = (
                supabase.table(CATEGORY_TABLE)
                .select("id,user_id,is_archived")
                .eq("id", category_id)
                .maybe_single()
                .execute()
            )
        except APIError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
        row = result.data if result is not None else None
        if not isinstance(row, dict) or bool(row.get("is_archived", False)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        owner = row.get("user_id")
        if owner is not None and int(owner) != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Category does not belong to this user")
        return int(row["id"])

    if category_name is not None:
        return _resolve_category_id_by_name(supabase, user_id, category_name)

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="category_id or category is required")


def _categories_by_ids(supabase: Client, ids: list[int]) -> dict[int, dict[str, Any]]:
    """Load category metadata keyed by category id."""
    if not ids:
        return {}
    unique_ids = list(dict.fromkeys(ids))
    try:
        result = (
            supabase.table(CATEGORY_TABLE)
            .select("id,name,icon,color_key")
            .in_("id", unique_ids)
            .execute()
        )
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    mapping: dict[int, dict[str, Any]] = {}
    for row in result.data or []:
        mapping[int(row["id"])] = row
    return mapping


def _alarm_rows_to_responses(supabase: Client, rows: list[dict[str, Any]]) -> list[AlarmResponse]:
    if not rows:
        return []
    cat_ids = [int(r["category"]) for r in rows]
    categories = _categories_by_ids(supabase, cat_ids)
    out: list[AlarmResponse] = []
    for row in rows:
        cid = int(row["category"])
        category = categories.get(cid)
        if category is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Category id {cid} has no row in the category table",
            )
        out.append(
            AlarmResponse.model_validate(
                {
                    **row,
                    "category": str(category.get("name") or ""),
                    "category_id": cid,
                    "category_icon": str(category.get("icon") or "⭐"),
                    "category_color_key": str(category.get("color_key") or "purple"),
                }
            )
        )
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
        err = str(e).lower()
        if "0 rows" in err or "pgrst116" in err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found") from e
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    row = result.data if result is not None else None
    if not isinstance(row, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found")
    return _alarm_rows_to_responses(supabase, [row])[0]


@router.post("/", response_model=AlarmResponse, status_code=status.HTTP_201_CREATED)
def create_alarm(payload: AlarmCreate, supabase: Client = Depends(get_supabase)) -> AlarmResponse:
    category_id = _resolve_category_id(supabase, payload.user_id, payload.category_id, payload.category)
    insert_payload = payload.model_dump(mode="json", exclude={"category", "category_id"})
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
    return _update_alarm_with_payload(alarm_id, payload, supabase)


@router.post("/{alarm_id}/update", response_model=AlarmResponse)
def update_alarm_via_post(
    alarm_id: int,
    payload: AlarmUpdate,
    supabase: Client = Depends(get_supabase),
) -> AlarmResponse:
    """POST compatibility endpoint for clients/proxies that reject PATCH."""
    return _update_alarm_with_payload(alarm_id, payload, supabase)


def _update_alarm_with_payload(
    alarm_id: int,
    payload: AlarmUpdate,
    supabase: Client,
) -> AlarmResponse:
    patch = payload.model_dump(mode="json", exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    if "category" in patch or "category_id" in patch:
        category_name = patch.pop("category", None)
        category_id = patch.pop("category_id", None)
        user_id = patch.get("user_id")
        if user_id is None:
            try:
                existing = (
                    supabase.table(ALARMS_TABLE)
                    .select("user_id")
                    .eq("id", alarm_id)
                    .maybe_single()
                    .execute()
                )
            except APIError as e:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
            row = existing.data if existing is not None else None
            if not isinstance(row, dict):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found")
            user_id = int(row["user_id"])
        patch["category"] = _resolve_category_id(supabase, int(user_id), category_id, category_name)
    return _run_alarm_update(supabase, alarm_id, patch)


@router.delete("/{alarm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alarm(alarm_id: int, supabase: Client = Depends(get_supabase)) -> None:
    _delete_alarm_by_id(alarm_id, supabase)


@router.post("/{alarm_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_alarm_via_post(alarm_id: int, supabase: Client = Depends(get_supabase)) -> None:
    """POST compatibility endpoint for clients/proxies that reject DELETE."""
    _delete_alarm_by_id(alarm_id, supabase)


def _delete_alarm_by_id(alarm_id: int, supabase: Client) -> None:
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
        delete_history_for_alarm(supabase, alarm_id)
        supabase.table(ALARMS_TABLE).delete().eq("id", alarm_id).execute()
    except APIError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
