"""Event-related command handlers: /addevent, /agenda."""

import uuid
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.bot.formatters import format_agenda, format_event
from secretary.bot.keyboards import confirm_create_event_keyboard, undo_keyboard
from secretary.bot.states import AddEventStates
from secretary.core.schemas import EventCreate, EventFilter, TaskFilter
from secretary.core import events as event_crud
from secretary.core import tasks as task_crud

router = Router()


# ---------------------------------------------------------------------------
# Datetime parsing helper
# ---------------------------------------------------------------------------


def _parse_datetime(text: str) -> datetime | None:
    """Parse datetime strings. Accepts natural language and ISO-like formats."""
    text = text.strip()
    now = datetime.now(timezone.utc)

    lower = text.lower()
    if lower in ("now",):
        return now

    # Try common formats
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d",
        "%H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%H:%M":
                # Time only -- assume today
                dt = now.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
            elif fmt == "%Y-%m-%d":
                # Date only -- assume start of day
                dt = dt.replace(hour=9, minute=0, tzinfo=timezone.utc)
                return dt
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # Natural language for date + time: "tomorrow 14:00", "friday 10:00"
    parts = lower.split()
    if len(parts) == 2:
        date_part, time_part = parts
        time_dt = None
        try:
            time_dt = datetime.strptime(time_part, "%H:%M")
        except ValueError:
            pass

        if time_dt is not None:
            today = now.replace(hour=time_dt.hour, minute=time_dt.minute, second=0, microsecond=0)

            if date_part in ("today",):
                return today
            if date_part in ("tomorrow", "tmr"):
                return today + timedelta(days=1)

            day_names = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
                "mon": 0,
                "tue": 1,
                "wed": 2,
                "thu": 3,
                "fri": 4,
                "sat": 5,
                "sun": 6,
            }
            if date_part in day_names:
                target = day_names[date_part]
                current = now.weekday()
                delta = (target - current) % 7
                if delta == 0:
                    delta = 7
                return today + timedelta(days=delta)

    return None


# ---------------------------------------------------------------------------
# /addevent  -- FSM flow
# ---------------------------------------------------------------------------


@router.message(Command("addevent"))
async def cmd_addevent(message: Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        title = args[1].strip()
        await state.update_data(title=title)
        await message.answer(
            f"Event: <b>{title}</b>\n\n"
            "When does it start?\n"
            "Examples: <code>tomorrow 14:00</code>, <code>2026-04-10 09:00</code>",
            parse_mode="HTML",
        )
        await state.set_state(AddEventStates.waiting_for_start)
        return

    await message.answer("What's the event title?")
    await state.set_state(AddEventStates.waiting_for_title)


@router.message(AddEventStates.waiting_for_title)
async def addevent_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not title:
        await message.answer("Please enter a non-empty title.")
        return
    await state.update_data(title=title)
    await message.answer(
        "When does it start?\nExamples: <code>tomorrow 14:00</code>, <code>2026-04-10 09:00</code>",
        parse_mode="HTML",
    )
    await state.set_state(AddEventStates.waiting_for_start)


@router.message(AddEventStates.waiting_for_start)
async def addevent_start(message: Message, state: FSMContext) -> None:
    start_at = _parse_datetime(message.text)
    if start_at is None:
        await message.answer(
            "Could not parse that datetime. Try formats like:\n"
            "<code>2026-04-10 14:00</code>\n"
            "<code>tomorrow 09:00</code>\n"
            "<code>friday 15:30</code>",
            parse_mode="HTML",
        )
        return

    await state.update_data(start_at=start_at.isoformat())
    await message.answer(
        f"Start: {start_at.strftime('%b %d, %H:%M')}\n\n"
        "When does it end?\n"
        "Examples: <code>15:00</code>, <code>2026-04-10 17:00</code>, or <code>+1h</code> for duration",
        parse_mode="HTML",
    )
    await state.set_state(AddEventStates.waiting_for_end)


@router.message(AddEventStates.waiting_for_end)
async def addevent_end(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    start_at = datetime.fromisoformat(data["start_at"])
    text = message.text.strip().lower()

    end_at = None

    # Duration shorthand: +1h, +30m, +1h30m
    if text.startswith("+"):
        dur = text[1:]
        hours = 0
        minutes = 0
        if "h" in dur:
            h_part, rest = dur.split("h", 1)
            hours = int(h_part) if h_part else 0
            dur = rest
        if "m" in dur:
            m_part = dur.replace("m", "")
            minutes = int(m_part) if m_part else 0
        elif dur.isdigit():
            minutes = int(dur)

        if hours or minutes:
            end_at = start_at + timedelta(hours=hours, minutes=minutes)

    if end_at is None:
        end_at = _parse_datetime(message.text)
        if end_at is None:
            await message.answer(
                "Could not parse end time. Try:\n<code>15:00</code>, <code>+1h</code>, <code>+90m</code>",
                parse_mode="HTML",
            )
            return
        # If only time was given and it's before start, it's probably same-day
        if end_at < start_at:
            end_at = end_at.replace(year=start_at.year, month=start_at.month, day=start_at.day)

    await state.update_data(end_at=end_at.isoformat())

    summary = (
        f"<b>New Event</b>\n"
        f"Title: {data['title']}\n"
        f"Start: {start_at.strftime('%b %d, %H:%M')}\n"
        f"End: {end_at.strftime('%b %d, %H:%M')}\n\n"
        f"Create this event?"
    )
    await message.answer(summary, reply_markup=confirm_create_event_keyboard(), parse_mode="HTML")
    await state.set_state(AddEventStates.waiting_for_confirm)


@router.callback_query(AddEventStates.waiting_for_confirm, F.data == "ecr:yes")
async def addevent_confirm_yes(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    start_at = datetime.fromisoformat(data["start_at"])
    end_at = datetime.fromisoformat(data["end_at"])

    event_data = EventCreate(
        title=data["title"],
        start_at=start_at,
        end_at=end_at,
        calendar_source="internal",
    )
    batch_id = str(uuid.uuid4())
    event = await event_crud.create_event(session, event_data, batch_id)
    await session.commit()

    await callback.message.edit_text(
        f"\u2705 Event created!\n\n{format_event(event)}",
        reply_markup=undo_keyboard(batch_id),
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer()


@router.callback_query(AddEventStates.waiting_for_confirm, F.data == "ecr:no")
async def addevent_confirm_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("\u274c Event creation cancelled.")
    await state.clear()
    await callback.answer()


# ---------------------------------------------------------------------------
# /agenda  -- day/week view
# ---------------------------------------------------------------------------


@router.message(Command("agenda"))
async def cmd_agenda(message: Message, session: AsyncSession) -> None:
    args = message.text.split(maxsplit=1)
    arg = args[1].strip().lower() if len(args) > 1 else "today"

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if arg in ("today",):
        start = today_start
        end = today_start + timedelta(days=1)
        label = "Today's Agenda"
    elif arg in ("tomorrow", "tmr"):
        start = today_start + timedelta(days=1)
        end = today_start + timedelta(days=2)
        label = "Tomorrow's Agenda"
    elif arg in ("week",):
        start = today_start
        end = today_start + timedelta(days=7)
        label = "This Week's Agenda"
    else:
        start = today_start
        end = today_start + timedelta(days=1)
        label = "Today's Agenda"

    event_filter = EventFilter(start_after=start, start_before=end)
    events = await event_crud.list_events(session, event_filter)

    task_filter = TaskFilter(due_after=start, due_before=end)
    tasks = await task_crud.list_tasks(session, task_filter)

    text = f"\ud83d\udcc5 <b>{label}</b>\n\n{format_agenda(events, tasks)}"
    await message.answer(text, parse_mode="HTML")
