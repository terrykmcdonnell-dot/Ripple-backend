from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AlarmHistoryStatus = Literal["missed", "dismissed", "snoozed"]


class AlarmHistoryUpsert(BaseModel):
    """Create or update one alarm occurrence row for the signed-in user's numeric id."""

    user_id: int
    alarm_id: int
    scheduled_fire_at: datetime
    status: AlarmHistoryStatus
    label: str = ""
    category: str = Field(default="", description="Category display label snapshot for History UI")
    action_at: Optional[datetime] = Field(
        default=None,
        description="When the user dismissed or snoozed; omitted defaults to now for those statuses",
    )
    snooze_minutes: Optional[int] = Field(default=None, description="Only meaningful when status is snoozed")


class AlarmHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    alarm_id: Optional[int] = None
    label: str
    category: str
    scheduled_fire_at: datetime
    status: AlarmHistoryStatus
    action_at: Optional[datetime] = None
    snooze_minutes: Optional[int] = None
