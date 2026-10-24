from datetime import datetime, timezone
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


_DATETIME_PREFIX_RE = re.compile(
    r"^\s*([0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}"
    r"(?::[0-9]{2}(?:\.[0-9]{1,6})?)?"
    r"(?:Z|[+-][0-9]{2}:?[0-9]{2})?)"
)


def _coerce_scheduled_at(value: object) -> object:
    """Accept common JS/iOS timestamp variants before Pydantic datetime parsing."""
    if not isinstance(value, str):
        return value

    raw = value.strip().strip('"').strip("'")
    match = _DATETIME_PREFIX_RE.match(raw)
    if match:
        raw = match.group(1)
    raw = raw.replace(" ", "T")
    # Python/Pydantic accept `+00:00` consistently; normalize JS `Z`.
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    # Normalize offsets like +0000 to +00:00.
    if re.search(r"[+-][0-9]{4}$", raw):
        raw = f"{raw[:-2]}:{raw[-2:]}"
    return raw


MAX_RING_TIMES = 6
MAX_SKIPPED_FIRES = 24
_RING_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


def _normalize_ring_times(value: list[str] | None) -> list[str] | None:
    """Local wall-clock "HH:mm" strings: validated, deduped, sorted, 1..6 entries."""
    if value is None:
        return None
    cleaned: set[str] = set()
    for item in value:
        text = str(item).strip()
        match = _RING_TIME_RE.match(text)
        if not match:
            raise ValueError(f"ring_times entries must be HH:mm (got {text!r})")
        cleaned.add(f"{match.group(1)}:{match.group(2)}")
    if not cleaned:
        raise ValueError("ring_times must contain at least one time")
    if len(cleaned) > MAX_RING_TIMES:
        raise ValueError(f"ring_times allows at most {MAX_RING_TIMES} times")
    return sorted(cleaned)


def _normalize_skipped_fires(value: list[str] | None) -> list[str] | None:
    """ISO occurrence instants the user skipped; deduped and capped (newest kept)."""
    if value is None:
        return None
    cleaned: dict[str, datetime] = {}
    for item in value:
        raw = _coerce_scheduled_at(str(item))
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError as e:
            raise ValueError(f"skipped_fires entries must be ISO timestamps (got {item!r})") from e
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        cleaned[str(item).strip()] = parsed
    ordered = sorted(cleaned.items(), key=lambda kv: kv[1])
    return [k for k, _ in ordered[-MAX_SKIPPED_FIRES:]]


class AlarmCreate(BaseModel):
    user_id: int
    label: str
    scheduled_at: datetime
    interval: int = Field(description="Repeat interval magnitude")
    unit: str
    category: str | None = Field(default=None, description="Legacy category name; resolved to id via the category table")
    category_id: int | None = Field(default=None, description="Preferred category id; must be system or owned by user")
    sound: str | None = Field(default=None, description="Human-readable preset name (app sound picker labels)")
    is_enabled: bool = True
    ring_times: list[str] | None = Field(
        default=None,
        description='Local wall-clock ring times ("HH:mm"), first entry matches scheduled_at; null = single-time',
    )
    skipped_fires: list[str] | None = Field(default=None, description="ISO occurrence instants skipped by the user")

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def normalize_scheduled_at(cls, value: object) -> object:
        return _coerce_scheduled_at(value)

    @field_validator("ring_times")
    @classmethod
    def validate_ring_times(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_ring_times(value)

    @field_validator("skipped_fires")
    @classmethod
    def validate_skipped_fires(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_skipped_fires(value)


class AlarmToggle(BaseModel):
    """Toggle alarm enabled state."""

    is_enabled: bool


class AlarmUpdate(BaseModel):
    user_id: Optional[int] = None
    label: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    interval: Optional[int] = None
    unit: Optional[str] = None
    is_enabled: Optional[bool] = None
    category: Optional[str] = Field(
        default=None,
        description="Category name; resolved to id via the category table",
    )
    category_id: Optional[int] = Field(default=None, description="Preferred category id; must be system or owned by user")
    sound: Optional[str] = Field(
        default=None,
        description="Human-readable preset name (app sound picker labels)",
    )
    ring_times: Optional[list[str]] = Field(
        default=None,
        description='Local wall-clock ring times ("HH:mm"); send null to make the alarm single-time',
    )
    skipped_fires: Optional[list[str]] = Field(default=None, description="ISO occurrence instants skipped by the user")

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def normalize_scheduled_at(cls, value: object) -> object:
        return _coerce_scheduled_at(value)

    @field_validator("ring_times")
    @classmethod
    def validate_ring_times(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_ring_times(value)

    @field_validator("skipped_fires")
    @classmethod
    def validate_skipped_fires(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_skipped_fires(value)


class AlarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    label: str
    scheduled_at: datetime
    interval: int = Field(description="Repeat interval magnitude")
    unit: str
    category: str = Field(description="Category display name from the category table")
    category_id: int
    category_icon: str = "⭐"
    category_color_key: str = "purple"
    is_enabled: bool
    sound: str | None = Field(default=None, description="Human-readable preset name stored on the alarm row")
    ring_times: list[str] | None = Field(default=None, description='Local wall-clock ring times ("HH:mm"); null = single-time')
    skipped_fires: list[str] | None = Field(default=None, description="ISO occurrence instants skipped by the user")
