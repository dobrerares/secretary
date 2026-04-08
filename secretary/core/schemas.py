from datetime import datetime
from pydantic import BaseModel, Field


# --- Task schemas ---


class SubtaskCreate(BaseModel):
    title: str
    is_complete: bool = False
    position: int = 0


class SubtaskUpdate(BaseModel):
    title: str | None = None
    is_complete: bool | None = None
    position: int | None = None


class SubtaskResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    task_id: int
    title: str
    is_complete: bool
    position: int


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    area: str | None = None
    priority: str = "none"
    status: str = "to_do"
    due_at: datetime | None = None
    scheduled_at: datetime | None = None
    time_estimate_minutes: int | None = None
    recurrence_rule: str | None = None
    source: str = "manual"
    inbox_item_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    subtasks: list[SubtaskCreate] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    area: str | None = None
    priority: str | None = None
    status: str | None = None
    due_at: datetime | None = None
    scheduled_at: datetime | None = None
    time_estimate_minutes: int | None = None
    recurrence_rule: str | None = None
    tags: list[str] | None = None
    subtasks: list[SubtaskCreate] | None = None


class TaskFilter(BaseModel):
    area: str | None = None
    priority: str | None = None
    status: str | None = None
    due_before: datetime | None = None
    due_after: datetime | None = None
    overdue: bool = False
    search: str | None = None
    tag: str | None = None


class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    title: str
    description: str | None
    area: str | None
    priority: str
    status: str
    due_at: datetime | None
    scheduled_at: datetime | None
    time_estimate_minutes: int | None
    recurrence_rule: str | None
    source: str
    inbox_item_id: int | None
    created_at: datetime
    updated_at: datetime
    subtasks: list[SubtaskResponse] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# --- Event schemas ---


class EventCreate(BaseModel):
    title: str
    description: str | None = None
    area: str | None = None
    start_at: datetime
    end_at: datetime
    location: str | None = None
    is_all_day: bool = False
    calendar_source: str = "internal"
    external_id: str | None = None
    recurrence_rule: str | None = None
    inbox_item_id: int | None = None


class EventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    area: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    location: str | None = None
    is_all_day: bool | None = None
    recurrence_rule: str | None = None


class EventFilter(BaseModel):
    area: str | None = None
    start_after: datetime | None = None
    start_before: datetime | None = None
    calendar_source: str | None = None


class EventResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    title: str
    description: str | None
    area: str | None
    start_at: datetime
    end_at: datetime
    location: str | None
    is_all_day: bool
    calendar_source: str
    external_id: str | None
    recurrence_rule: str | None
    inbox_item_id: int | None
    created_at: datetime
    updated_at: datetime


# --- Inbox schemas ---


class InboxItemCreate(BaseModel):
    raw_text: str
    source: str = "chat"


class InboxItemResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    raw_text: str
    source: str
    status: str
    proposed_actions: dict | list | None
    batch_id: str | None
    created_at: datetime


# --- Settings schemas ---


class SettingsUpdate(BaseModel):
    wake_time: str | None = None
    wind_down_time: str | None = None
    notification_level: str | None = None
    auto_approve_mode: str | None = None
    timezone: str | None = None
    areas: list[str] | None = None
    memory: list[str] | None = None
    undo_expiry_minutes: int | None = None
    ai_context_messages: int | None = None


class SettingsResponse(BaseModel):
    model_config = {"from_attributes": True}
    wake_time: str
    wind_down_time: str
    notification_level: str
    auto_approve_mode: str
    timezone: str
    areas: list
    memory: list
    undo_expiry_minutes: int
    ai_context_messages: int


# --- Action Log schemas ---


class ActionLogResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    action_type: str
    entity_type: str
    entity_id: int
    batch_id: str
    is_undone: bool
    created_at: datetime
    expires_at: datetime
