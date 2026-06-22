from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CategoryCreate(BaseModel):
    user_id: int
    name: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="⭐", min_length=1, max_length=8)
    color_key: str = Field(default="purple", max_length=20)
    sort_order: int = 100

    @field_validator("name", "icon", "color_key")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class CategoryUpdate(BaseModel):
    user_id: int
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    icon: Optional[str] = Field(default=None, min_length=1, max_length=8)
    color_key: Optional[str] = Field(default=None, max_length=20)
    sort_order: Optional[int] = None

    @field_validator("name", "icon", "color_key")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else value


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    name: str
    icon: str = "⭐"
    color_key: str = "purple"
    sort_order: int = 100
    is_system: bool = False
    is_archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CategoryDeleteResponse(BaseModel):
    deleted: bool
    reassigned_alarm_count: int = 0
