"""Text formatters for Telegram message display."""

from datetime import datetime, timezone


_PRIORITY_EMOJI = {
    "none": "",
    "low": "\ud83d\udfe2",
    "medium": "\ud83d\udfe1",
    "high": "\ud83d\udfe0",
    "urgent": "\ud83d\udd34",
}

_STATUS_EMOJI = {
    "inbox": "\ud83d\udce5",
    "to_do": "\u2b1c",
    "in_progress": "\ud83d\udfe6",
    "done": "\u2705",
    "cancelled": "\u274c",
}


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%b %d, %H:%M")


def _fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%b %d")


def _due_label(due_at: datetime | None) -> str:
    if due_at is None:
        return ""
    now = datetime.now(timezone.utc)
    if due_at < now:
        return f" \u26a0\ufe0f OVERDUE ({_fmt_date(due_at)})"
    return f" \ud83d\udcc5 {_fmt_date(due_at)}"


def format_task(task) -> str:
    """Format a single task for rich display."""
    pri = _PRIORITY_EMOJI.get(task.priority, "")
    status = _STATUS_EMOJI.get(task.status, "\u2b1c")
    due = _due_label(task.due_at)
    area = f" [{task.area}]" if task.area else ""

    lines = [f"{status} <b>{task.title}</b>{area}"]

    meta_parts = []
    if pri:
        meta_parts.append(f"{pri} {task.priority.capitalize()}")
    meta_parts.append(f"ID: {task.id}")
    if due:
        meta_parts.append(due.strip())
    if meta_parts:
        lines.append("  ".join(meta_parts))

    if task.description:
        desc = task.description[:200]
        if len(task.description) > 200:
            desc += "..."
        lines.append(f"\ud83d\udcdd {desc}")

    if hasattr(task, "subtasks") and task.subtasks:
        for st in task.subtasks:
            check = "\u2705" if st.is_complete else "\u2b1c"
            lines.append(f"  {check} {st.title}")

    if hasattr(task, "tags") and task.tags:
        tag_str = " ".join(f"#{t.name}" for t in task.tags)
        lines.append(f"\ud83c\udff7 {tag_str}")

    return "\n".join(lines)


def format_task_list(tasks: list) -> str:
    """Format a numbered list of tasks."""
    if not tasks:
        return "\ud83d\udcad No tasks found."

    lines = []
    for i, task in enumerate(tasks, 1):
        pri = _PRIORITY_EMOJI.get(task.priority, "")
        status = _STATUS_EMOJI.get(task.status, "\u2b1c")
        due = _due_label(task.due_at)
        area = f" [{task.area}]" if task.area else ""
        pri_str = f" {pri}" if pri else ""

        lines.append(f"{i}. {status}{pri_str} <b>{task.title}</b>{area}{due}  <code>#{task.id}</code>")

    lines.append(f"\n\ud83d\udccb {len(tasks)} task(s)")
    return "\n".join(lines)


def format_event(event) -> str:
    """Format a single event for display."""
    if event.is_all_day:
        time_str = "\ud83c\udf1e All day"
    else:
        start = event.start_at.strftime("%H:%M")
        end = event.end_at.strftime("%H:%M")
        time_str = f"\ud83d\udd52 {start} - {end}"

    area = f" [{event.area}]" if event.area else ""
    lines = [f"\ud83d\udcc6 <b>{event.title}</b>{area}", f"  {time_str}"]

    if event.location:
        lines.append(f"  \ud83d\udccd {event.location}")
    if event.description:
        desc = event.description[:200]
        lines.append(f"  \ud83d\udcdd {desc}")

    lines.append(f"  ID: {event.id}")
    return "\n".join(lines)


def format_event_list(events: list) -> str:
    """Format a list of events."""
    if not events:
        return "\ud83d\udcc6 No events."
    return "\n\n".join(format_event(e) for e in events)


def format_agenda(events: list, tasks: list) -> str:
    """Format a combined day view with events and tasks."""
    parts = []

    if events:
        parts.append("\ud83d\udcc6 <b>Events</b>")
        for e in events:
            if e.is_all_day:
                parts.append(f"  \ud83c\udf1e <b>{e.title}</b>")
            else:
                t = e.start_at.strftime("%H:%M")
                parts.append(f"  {t}  <b>{e.title}</b>")
                if e.location:
                    parts.append(f"        \ud83d\udccd {e.location}")
    else:
        parts.append("\ud83d\udcc6 <b>Events</b>\n  No events scheduled.")

    parts.append("")

    if tasks:
        parts.append("\u2705 <b>Tasks Due</b>")
        for i, task in enumerate(tasks, 1):
            pri = _PRIORITY_EMOJI.get(task.priority, "")
            pri_str = f" {pri}" if pri else ""
            parts.append(f"  {i}.{pri_str} {task.title}  <code>#{task.id}</code>")
    else:
        parts.append("\u2705 <b>Tasks Due</b>\n  No tasks due.")

    return "\n".join(parts)


def format_inbox_item(item) -> str:
    """Format an inbox item for display."""
    status_map = {
        "pending": "\ud83d\udfe1",
        "proposed": "\ud83d\udfe0",
        "processed": "\u2705",
        "rejected": "\u274c",
    }
    emoji = status_map.get(item.status, "\u2b1c")
    text = item.raw_text[:300]
    if len(item.raw_text) > 300:
        text += "..."
    return f"{emoji} #{item.id} [{item.status}] ({item.source})\n{text}"
