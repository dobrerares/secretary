"""Validation helpers for proposed actions and auto-approve decisions."""

from datetime import datetime

# Tool calls that destroy data. In standard mode these require explicit approval;
# in aggressive/silent mode they may be auto-approved if validation passes.
_DESTRUCTIVE_TOOLS = {"delete_task", "delete_event"}


def is_destructive(action: dict) -> bool:
    """Return True if the action is destructive (deletes data)."""
    tool = action.get("tool", "")
    return tool in _DESTRUCTIVE_TOOLS


def validate_proposed_action(action: dict, areas: list[str]) -> bool:
    """Check whether a proposed action has valid structure and data.

    Returns True if the action passes all validation checks and is safe
    for auto-approval (assuming the auto-approve mode allows it).
    """
    tool = action.get("tool")
    args = action.get("args")

    if not tool or not isinstance(tool, str):
        return False
    if args is not None and not isinstance(args, dict):
        return False

    args = args or {}

    # Per-tool validation
    if tool == "delete_task":
        if not _has_positive_int(args, "task_id"):
            return False

    elif tool == "delete_event":
        if not _has_positive_int(args, "event_id"):
            return False

    elif tool == "create_task":
        if not _has_non_empty_string(args, "title"):
            return False
        if not _valid_area_if_present(args, areas):
            return False
        if not _valid_dates_if_present(args, "due_at", "scheduled_at"):
            return False

    elif tool == "update_task":
        if not _has_positive_int(args, "task_id"):
            return False
        if not _valid_area_if_present(args, areas):
            return False
        if not _valid_dates_if_present(args, "due_at", "scheduled_at"):
            return False

    elif tool == "complete_task":
        if not _has_positive_int(args, "task_id"):
            return False

    elif tool == "create_event":
        if not _has_non_empty_string(args, "title"):
            return False
        if not _valid_iso_date(args.get("start_at")):
            return False
        if not _valid_iso_date(args.get("end_at")):
            return False
        if not _valid_area_if_present(args, areas):
            return False

    elif tool == "update_event":
        if not _has_positive_int(args, "event_id"):
            return False
        if not _valid_area_if_present(args, areas):
            return False
        if not _valid_dates_if_present(args, "start_at", "end_at"):
            return False

    elif tool == "list_tasks":
        if not _valid_dates_if_present(args, "due_before", "due_after"):
            return False

    elif tool == "list_events":
        if not _valid_dates_if_present(args, "start_after", "start_before"):
            return False

    elif tool == "get_briefing":
        briefing_type = args.get("type")
        if briefing_type and briefing_type not in ("daily", "weekly"):
            return False

    elif tool == "read_settings":
        pass  # no args needed

    elif tool == "update_memory":
        if not _has_non_empty_string(args, "fact"):
            return False

    else:
        # Unknown tool -- fail validation
        return False

    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_non_empty_string(args: dict, key: str) -> bool:
    """Check that args[key] is a non-empty string."""
    val = args.get(key)
    return isinstance(val, str) and len(val.strip()) > 0


def _has_positive_int(args: dict, key: str) -> bool:
    """Check that args[key] is a positive integer."""
    val = args.get(key)
    if isinstance(val, int) and val > 0:
        return True
    # Accept string-encoded ints from LLM
    if isinstance(val, str):
        try:
            return int(val) > 0
        except ValueError:
            return False
    return False


def _valid_iso_date(value) -> bool:
    """Return True if value is a valid ISO 8601 datetime string."""
    if not value or not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _valid_dates_if_present(args: dict, *keys: str) -> bool:
    """Validate that any date fields present in args are valid ISO strings."""
    for key in keys:
        val = args.get(key)
        if val is not None and not _valid_iso_date(val):
            return False
    return True


def _valid_area_if_present(args: dict, areas: list[str]) -> bool:
    """If area is set, check it matches a known area (or areas is empty)."""
    area = args.get("area")
    if area is None:
        return True
    if not areas:
        # No areas configured -- accept anything
        return True
    return area in areas
