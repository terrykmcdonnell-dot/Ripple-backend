from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.schemas.category import CategoryCreate, CategoryDeleteResponse, CategoryResponse, CategoryUpdate
from app.supabase_db import get_supabase

router = APIRouter(prefix="/api/categories", tags=["categories"])

CATEGORY_TABLE = "category"
ALARMS_TABLE = "alarms"


def _api_error(exc: APIError, context: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"{context}: {exc}")


def _normalize_row(row: dict[str, Any]) -> CategoryResponse:
    return CategoryResponse.model_validate(
        {
            **row,
            "icon": row.get("icon") or "⭐",
            "color_key": row.get("color_key") or "purple",
            "sort_order": row.get("sort_order") if row.get("sort_order") is not None else 100,
            "is_system": row.get("user_id") is None,
            "is_archived": bool(row.get("is_archived", False)),
        }
    )


def _fetch_category(supabase: Client, category_id: int) -> dict[str, Any] | None:
    try:
        result = (
            supabase.table(CATEGORY_TABLE)
            .select("*")
            .eq("id", category_id)
            .maybe_single()
            .execute()
        )
    except APIError as e:
        raise _api_error(e, "category lookup") from e
    row = result.data if result is not None else None
    return row if isinstance(row, dict) else None


def _assert_user_category(row: dict[str, Any], user_id: int) -> None:
    if row.get("user_id") is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System categories cannot be changed")
    if int(row["user_id"]) != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Category does not belong to this user")


def _assert_category_available(supabase: Client, category_id: int, user_id: int) -> dict[str, Any]:
    row = _fetch_category(supabase, category_id)
    if row is None or bool(row.get("is_archived", False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    owner = row.get("user_id")
    if owner is not None and int(owner) != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Category does not belong to this user")
    return row


@router.get("/", response_model=list[CategoryResponse])
def list_categories(
    user_id: int = Query(..., description="public.users.id"),
    supabase: Client = Depends(get_supabase),
) -> list[CategoryResponse]:
    try:
        result = (
            supabase.table(CATEGORY_TABLE)
            .select("*")
            .or_(f"user_id.is.null,user_id.eq.{user_id}")
            .eq("is_archived", False)
            .order("sort_order")
            .order("name")
            .execute()
        )
    except APIError as e:
        raise _api_error(e, "category list") from e
    return [_normalize_row(row) for row in result.data or []]


@router.post("/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, supabase: Client = Depends(get_supabase)) -> CategoryResponse:
    body = payload.model_dump(mode="json")
    body["is_archived"] = False
    try:
        inserted = supabase.table(CATEGORY_TABLE).insert(body).execute()
    except APIError as e:
        raise _api_error(e, "category create") from e
    rows = inserted.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Category insert returned no row")
    return _normalize_row(rows[0])


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    supabase: Client = Depends(get_supabase),
) -> CategoryResponse:
    existing = _fetch_category(supabase, category_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    _assert_user_category(existing, payload.user_id)

    patch = payload.model_dump(mode="json", exclude_unset=True, exclude={"user_id"})
    if not patch:
        return _normalize_row(existing)
    try:
        updated = supabase.table(CATEGORY_TABLE).update(patch).eq("id", category_id).execute()
    except APIError as e:
        raise _api_error(e, "category update") from e
    rows = updated.data or []
    return _normalize_row(rows[0] if rows else {**existing, **patch})


@router.delete("/{category_id}", response_model=CategoryDeleteResponse)
def delete_category(
    category_id: int,
    user_id: int = Query(..., description="public.users.id"),
    reassign_to_category_id: int | None = Query(default=None),
    supabase: Client = Depends(get_supabase),
) -> CategoryDeleteResponse:
    existing = _fetch_category(supabase, category_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    _assert_user_category(existing, user_id)

    try:
        alarm_result = (
            supabase.table(ALARMS_TABLE)
            .select("id")
            .eq("user_id", user_id)
            .eq("category", category_id)
            .execute()
        )
    except APIError as e:
        raise _api_error(e, "category alarm usage lookup") from e
    used_alarm_ids = [int(row["id"]) for row in alarm_result.data or []]

    reassigned_count = 0
    if used_alarm_ids:
        if reassign_to_category_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Category is used by alarms; provide reassign_to_category_id",
            )
        if reassign_to_category_id == category_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot reassign to same category")
        _assert_category_available(supabase, reassign_to_category_id, user_id)
        try:
            updated = (
                supabase.table(ALARMS_TABLE)
                .update({"category": reassign_to_category_id})
                .eq("user_id", user_id)
                .eq("category", category_id)
                .execute()
            )
        except APIError as e:
            raise _api_error(e, "category alarm reassignment") from e
        reassigned_count = len(updated.data or used_alarm_ids)

    try:
        supabase.table(CATEGORY_TABLE).update({"is_archived": True}).eq("id", category_id).execute()
    except APIError as e:
        raise _api_error(e, "category delete") from e

    return CategoryDeleteResponse(deleted=True, reassigned_alarm_count=reassigned_count)


@router.post("/{category_id}/delete", response_model=CategoryDeleteResponse)
def delete_category_via_post(
    category_id: int,
    user_id: int = Query(..., description="public.users.id"),
    reassign_to_category_id: int | None = Query(default=None),
    supabase: Client = Depends(get_supabase),
) -> CategoryDeleteResponse:
    """POST compatibility endpoint for clients/proxies that reject DELETE."""
    return delete_category(category_id, user_id, reassign_to_category_id, supabase)
