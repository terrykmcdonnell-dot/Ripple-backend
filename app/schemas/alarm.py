from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AlarmCreate(BaseModel):
    user_id: int
    label: str
    scheduled_at: datetime
    interval: int = Field(description="Repeat interval magnitude")
    unit: str
    category: str = Field(description="Category name; resolved to id via the category table")
    is_enabled: bool = True


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
