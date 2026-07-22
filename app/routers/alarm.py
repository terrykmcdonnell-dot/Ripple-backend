
from app.routers.alarm_history import delete_history_for_alarm
def _resolve_category_id_by_name(supabase: Client, user_id: int, name: str) -> int:
    clean = name.strip()
    if not clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="category is required")
            .or_(f"user_id.is.null,user_id.eq.{user_id}")
            .eq("is_archived", False)
            .ilike("name", clean)
    rows = result.data or []
    if not rows:
            detail=f'Category "{clean}" not found',
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
            .select("id,name,icon,color_key")
    mapping: dict[int, dict[str, Any]] = {}
        mapping[int(row["id"])] = row
    categories = _categories_by_ids(supabase, cat_ids)
        category = categories.get(cid)
        if category is None:
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
    category_id = _resolve_category_id(supabase, payload.user_id, payload.category_id, payload.category)
    insert_payload = payload.model_dump(mode="json", exclude={"category", "category_id"})
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
        delete_history_for_alarm(supabase, alarm_id)