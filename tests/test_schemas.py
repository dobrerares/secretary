"""Tests covering structural validation in core/schemas.py.

These tests assert that Pydantic is the single source of truth for the
structural validity of inbound data: bad strings, bad ID values, and bad
enum values must be rejected at construction time.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from secretary.core.schemas import (
    EventCreate,
    EventDeleteArgs,
    EventUpdate,
    EventUpdateArgs,
    SettingsUpdate,
    TaskCompleteArgs,
    TaskCreate,
    TaskDeleteArgs,
    TaskUpdate,
    TaskUpdateArgs,
)


# --- TaskCreate: title min_length, priority/status/source enums, datetime parsing ---


def test_task_create_rejects_empty_title():
    with pytest.raises(ValidationError):
        TaskCreate(title="")


def test_task_create_rejects_invalid_priority():
    with pytest.raises(ValidationError):
        TaskCreate(title="x", priority="really high")


def test_task_create_rejects_invalid_due_at():
    with pytest.raises(ValidationError):
        TaskCreate(title="x", due_at="not a date")


def test_task_create_rejects_invalid_status():
    with pytest.raises(ValidationError):
        TaskCreate(title="x", status="invalid")


def test_task_create_rejects_invalid_source():
    with pytest.raises(ValidationError):
        TaskCreate(title="x", source="not_a_source")


def test_task_create_accepts_valid_priority_values():
    for priority in ("none", "low", "medium", "high", "urgent"):
        TaskCreate(title="x", priority=priority)


def test_task_create_accepts_valid_status_values():
    for status in ("inbox", "to_do", "in_progress", "done", "cancelled"):
        TaskCreate(title="x", status=status)


def test_task_create_accepts_iso_datetime():
    TaskCreate(title="x", due_at="2025-01-02T15:04:05+00:00")


# --- TaskUpdate: same enum tightness ---


def test_task_update_rejects_invalid_priority():
    with pytest.raises(ValidationError):
        TaskUpdate(priority="ultra-mega")


def test_task_update_rejects_invalid_status():
    with pytest.raises(ValidationError):
        TaskUpdate(status="not-a-status")


# --- EventCreate: title min_length, calendar_source enum ---


def test_event_create_rejects_empty_title():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        EventCreate(title="", start_at=now, end_at=now + timedelta(hours=1))


def test_event_create_rejects_invalid_calendar_source():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        EventCreate(
            title="Meeting",
            start_at=now,
            end_at=now + timedelta(hours=1),
            calendar_source="bogus",
        )


def test_event_create_rejects_invalid_start_at():
    with pytest.raises(ValidationError):
        EventCreate(title="Meeting", start_at="not a date", end_at="2025-01-02T01:00:00+00:00")


def test_event_update_rejects_invalid_dates():
    with pytest.raises(ValidationError):
        EventUpdate(start_at="bogus")


# --- SettingsUpdate: enum aliases for notification_level, auto_approve_mode ---


def test_settings_update_rejects_invalid_notification_level():
    with pytest.raises(ValidationError):
        SettingsUpdate(notification_level="screaming")


def test_settings_update_rejects_invalid_auto_approve_mode():
    with pytest.raises(ValidationError):
        SettingsUpdate(auto_approve_mode="yolo")


def test_settings_update_accepts_valid_modes():
    SettingsUpdate(auto_approve_mode="off")
    SettingsUpdate(auto_approve_mode="standard")
    SettingsUpdate(auto_approve_mode="aggressive")
    SettingsUpdate(auto_approve_mode="silent")


# --- Tool-args schemas: positive ID constraint ---


def test_task_delete_args_rejects_zero_task_id():
    with pytest.raises(ValidationError):
        TaskDeleteArgs(task_id=0)


def test_task_delete_args_rejects_negative_task_id():
    with pytest.raises(ValidationError):
        TaskDeleteArgs(task_id=-1)


def test_task_delete_args_accepts_positive_task_id():
    args = TaskDeleteArgs(task_id=42)
    assert args.task_id == 42


def test_task_complete_args_rejects_zero_task_id():
    with pytest.raises(ValidationError):
        TaskCompleteArgs(task_id=0)


def test_task_update_args_rejects_zero_task_id():
    with pytest.raises(ValidationError):
        TaskUpdateArgs(task_id=0)


def test_task_update_args_rejects_invalid_priority():
    with pytest.raises(ValidationError):
        TaskUpdateArgs(task_id=1, priority="not-a-priority")


def test_event_delete_args_rejects_zero_event_id():
    with pytest.raises(ValidationError):
        EventDeleteArgs(event_id=0)


def test_event_update_args_rejects_negative_event_id():
    with pytest.raises(ValidationError):
        EventUpdateArgs(event_id=-5)


# --- area_is_known semantics preserved (now lives in core.schemas) ---


def test_area_is_known_none_area_is_always_ok():
    from secretary.core.schemas import area_is_known

    assert area_is_known(None, ["work", "personal"]) is True


def test_area_is_known_empty_user_areas_accepts_any():
    from secretary.core.schemas import area_is_known

    assert area_is_known("anything", []) is True


def test_area_is_known_rejects_unknown_area():
    from secretary.core.schemas import area_is_known

    assert area_is_known("mystery", ["work", "personal"]) is False


def test_area_is_known_accepts_known_area():
    from secretary.core.schemas import area_is_known

    assert area_is_known("work", ["work", "personal"]) is True


# --- secretary.ai.validation module is deleted entirely ---
#
# Issue #4 collapsed the auto-approve gate into ai/approval.py and moved the
# remaining domain helper (area_is_known) into core/schemas.py. Importing the
# old module must now fail.


def test_ai_validation_module_is_gone():
    import pytest

    with pytest.raises(ImportError):
        import secretary.ai.validation  # noqa: F401
