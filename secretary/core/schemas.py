from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- Enum aliases (single source of truth for valid string values) ---
#
# These Literal aliases mirror the CHECK constraints in secretary/db/models.py
# and the JSON-schema `enum` arrays in secretary/ai/tools.py. Any drift between
# those three places is a bug; keep them aligned.

Priority = Literal["none", "low", "medium", "high", "urgent"]
TaskStatus = Literal["inbox", "to_do", "in_progress", "done", "cancelled"]
TaskSource = Literal["chat", "voice", "quick_add", "manual", "ai_suggested"]
BriefingType = Literal["daily", "weekly"]
EventCalendarSource = Literal["google", "apple", "caldav", "internal"]
AutoApproveMode = Literal["off", "standard", "aggressive", "silent"]
NotificationLevel = Literal["minimal", "balanced", "aggressive"]


# --- Task schemas ---


class SubtaskCreate(BaseModel):
    title: str = Field(min_length=1)
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
    title: str = Field(min_length=1)
    description: str | None = None
    area: str | None = None
    priority: Priority = "none"
    status: TaskStatus = "to_do"
    due_at: datetime | None = None
    scheduled_at: datetime | None = None
    time_estimate_minutes: int | None = None
    recurrence_rule: str | None = None
    source: TaskSource = "manual"
    inbox_item_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    subtasks: list[SubtaskCreate] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    area: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    due_at: datetime | None = None
    scheduled_at: datetime | None = None
    time_estimate_minutes: int | None = None
    recurrence_rule: str | None = None
    tags: list[str] | None = None
    subtasks: list[SubtaskCreate] | None = None


class TaskFilter(BaseModel):
    area: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
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
    priority: Priority
    status: TaskStatus
    due_at: datetime | None
    scheduled_at: datetime | None
    time_estimate_minutes: int | None
    recurrence_rule: str | None
    source: TaskSource
    inbox_item_id: int | None
    created_at: datetime
    updated_at: datetime
    subtasks: list[SubtaskResponse] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# --- Event schemas ---


class EventCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    area: str | None = None
    start_at: datetime
    end_at: datetime
    location: str | None = None
    is_all_day: bool = False
    calendar_source: EventCalendarSource = "internal"
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
    calendar_source: EventCalendarSource | None = None


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
    calendar_source: EventCalendarSource
    external_id: str | None
    recurrence_rule: str | None
    inbox_item_id: int | None
    created_at: datetime
    updated_at: datetime


# --- Inbox schemas ---


class InboxItemCreate(BaseModel):
    raw_text: str = Field(min_length=1)
    source: Literal["chat", "voice", "quick_add"] = "chat"


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
    notification_level: NotificationLevel | None = None
    auto_approve_mode: AutoApproveMode | None = None
    timezone: str | None = None
    areas: list[str] | None = None
    memory: list[str] | None = None
    undo_expiry_minutes: int | None = None
    ai_context_messages: int | None = None


class SettingsResponse(BaseModel):
    model_config = {"from_attributes": True}
    wake_time: str
    wind_down_time: str
    notification_level: NotificationLevel
    auto_approve_mode: AutoApproveMode
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


# --- Tool-args schemas -------------------------------------------------------
#
# These are the structural contracts for the `args` payload of each LLM tool
# call (see secretary/ai/tools.py). They mirror what the LLM is told it can
# send. Issue #3 will register them in a proper Tool registry; for now they
# back the per-tool dispatcher used by the auto-approve gate.

# Re-use the full creation schemas as the args contract where they line up.
TaskCreateArgs = TaskCreate
EventCreateArgs = EventCreate


class TaskUpdateArgs(BaseModel):
    """Args for the `update_task` tool call."""

    task_id: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    area: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    due_at: datetime | None = None
    scheduled_at: datetime | None = None
    time_estimate_minutes: int | None = None
    tags: list[str] | None = None


class TaskCompleteArgs(BaseModel):
    """Args for the `complete_task` tool call."""

    task_id: int = Field(gt=0)


class TaskDeleteArgs(BaseModel):
    """Args for the `delete_task` tool call."""

    task_id: int = Field(gt=0)


class EventUpdateArgs(BaseModel):
    """Args for the `update_event` tool call."""

    event_id: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    area: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    location: str | None = None
    is_all_day: bool | None = None


class EventDeleteArgs(BaseModel):
    """Args for the `delete_event` tool call."""

    event_id: int = Field(gt=0)


class ListTasksArgs(BaseModel):
    """Args for the `list_tasks` tool call."""

    area: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    due_before: datetime | None = None
    due_after: datetime | None = None
    overdue: bool | None = None
    search: str | None = None


class ListEventsArgs(BaseModel):
    """Args for the `list_events` tool call."""

    area: str | None = None
    start_after: datetime | None = None
    start_before: datetime | None = None


class GetBriefingArgs(BaseModel):
    """Args for the `get_briefing` tool call."""

    type: BriefingType


class ReadSettingsArgs(BaseModel):
    """Args for the `read_settings` tool call (no required fields)."""


class UpdateMemoryArgs(BaseModel):
    """Args for the `update_memory` tool call."""

    fact: str = Field(min_length=1)
