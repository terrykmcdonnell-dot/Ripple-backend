from datetime import datetime
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


class AlarmCreate(BaseModel):
    user_id: int
    label: str
    scheduled_at: datetime
    interval: int = Field(description="Repeat interval magnitude")
    unit: str
    category: str = Field(description="Category name; resolved to id via the category table")
    sound: str | None = Field(default=None, description="Human-readable preset name (app sound picker labels)")
    is_enabled: bool = True

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def normalize_scheduled_at(cls, value: object) -> object:
        return _coerce_scheduled_at(value)


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
    sound: Optional[str] = Field(
        default=None,
        description="Human-readable preset name (app sound picker labels)",
    )

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def normalize_scheduled_at(cls, value: object) -> object:
        return _coerce_scheduled_at(value)


class AlarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    label: str
    scheduled_at: datetime
    interval: int = Field(description="Repeat interval magnitude")
    unit: str
    category: str = Field(description="Category display name from the category table")
    is_enabled: bool
    sound: str | None = Field(default=None, description="Human-readable preset name stored on the alarm row")
