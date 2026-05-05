"""System command handlers: /help, /undo, /inbox, /settings, /briefing."""

import uuid

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.bot.states import OnboardStates

from secretary.bot.formatters import format_inbox_item
from secretary.bot.keyboards import confirm_keyboard
from secretary.core.actions import get_last_batch_id, get_recent_actions
from secretary.core.inbox import list_pending
from secretary.core.settings import get_settings as get_db_settings

router = Router()


# ---------------------------------------------------------------------------
# /start & /help
# ---------------------------------------------------------------------------

HELP_TEXT = """\
<b>Secretary Bot</b> -- Your personal task manager

<b>Tasks</b>
/addtask -- Add a new task (interactive)
/tasks -- List active tasks
/tasks today -- Tasks due today
/tasks overdue -- Overdue tasks
/tasks &lt;area&gt; -- Filter by area
/done &lt;id&gt; -- Mark a task complete
/edit &lt;id&gt; -- Edit a task
/delete &lt;id&gt; -- Delete a task

<b>Events</b>
/addevent -- Add a new event (interactive)
/agenda -- Today's agenda
/agenda tomorrow -- Tomorrow's agenda
/agenda week -- This week's agenda

<b>System</b>
/inbox -- View pending inbox items
/undo -- Undo the last action
/sync -- Sync calendars now
/settings -- View current settings
/briefing -- Daily briefing (coming soon)
/help -- Show this help message

<b>Tips</b>
- You can add a title inline: <code>/addtask Buy groceries</code>
- Use <code>#id</code> or just the number: <code>/done 5</code> or <code>/done #5</code>
- Keywords work too: <code>/done groceries</code>
"""


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user_settings = await get_db_settings(session)
    has_areas = bool(user_settings.areas and len(user_settings.areas) > 0)

    if has_areas:
        await message.answer(
            "\U0001f44b Welcome back! Use /help to see commands, "
            "or just send me a message.",
            parse_mode="HTML",
        )
        return

    # First-time onboarding
    await message.answer(
        "\U0001f44b <b>Welcome to Secretary!</b>\n\n"
        "I'm your AI personal secretary. I'll help you manage "
        "tasks, events, and daily logistics.\n\n"
        "<b>How it works:</b>\n"
        "1\ufe0f\u20e3 Send me anything — tasks, reminders, brain dumps\n"
        "2\ufe0f\u20e3 I parse it and suggest structured items\n"
        "3\ufe0f\u20e3 You approve, edit, or reject\n\n"
        "Let's get started! Send me the areas of your life "
        "you want to organize, separated by commas:\n\n"
        "<code>Work, University, Personal, Health</code>",
        parse_mode="HTML",
    )
    await state.set_state(OnboardStates.waiting_for_areas)


@router.message(OnboardStates.waiting_for_areas)
async def onboard_receive_areas(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Please send your areas as a comma-separated list.")
        return

    areas = [a.strip() for a in message.text.split(",") if a.strip()]
    if not areas:
        await message.answer("I didn't catch any areas. Try: <code>Work, Personal, Health</code>", parse_mode="HTML")
        return

    from secretary.core.schemas import SettingsUpdate
    from secretary.core.settings import update_settings
    await update_settings(session, SettingsUpdate(areas=areas))
    await session.commit()
    await state.clear()

    area_list = ", ".join(f"<b>{a}</b>" for a in areas)
    await message.answer(
        f"\u2705 Areas set: {area_list}\n\n"
        "You're all set! Here's what you can do:\n\n"
        "\u2022 Send me a message like <i>\"Submit ISS project by Friday\"</i>\n"
        "\u2022 Use /addtask for a step-by-step flow\n"
        "\u2022 Use /agenda to see your day\n"
        "\u2022 Use /help for all commands\n\n"
        "Try sending me something now!",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML")


# ---------------------------------------------------------------------------
# /undo
# ---------------------------------------------------------------------------

@router.message(Command("undo"))
async def cmd_undo(message: Message, session: AsyncSession) -> None:
    batch_id = await get_last_batch_id(session)
    if not batch_id:
        await message.answer("Nothing to undo.")
        return

    # Show what will be undone
    actions = await get_recent_actions(session, limit=10)
    batch_actions = [a for a in actions if a.batch_id == batch_id]

    if not batch_actions:
        await message.answer("Nothing to undo.")
        return

    lines = ["\u26a0\ufe0f <b>Undo last action?</b>\n"]
    for a in batch_actions:
        entity_name = ""
        if a.after_state and "title" in a.after_state:
            entity_name = f' "{a.after_state["title"]}"'
        elif a.before_state and "title" in a.before_state:
            entity_name = f' "{a.before_state["title"]}"'
        lines.append(f"  {a.action_type.capitalize()} {a.entity_type}{entity_name}")

    await message.answer(
        "\n".join(lines),
        reply_markup=confirm_keyboard("undo", batch_id[:20]),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /inbox
# ---------------------------------------------------------------------------

@router.message(Command("inbox"))
async def cmd_inbox(message: Message, session: AsyncSession) -> None:
    items = await list_pending(session)
    if not items:
        await message.answer("\ud83d\udce5 Inbox is empty. Nice!")
        return

    lines = [f"\ud83d\udce5 <b>Inbox</b> ({len(items)} pending)\n"]
    for item in items:
        lines.append(format_inbox_item(item))
        lines.append("")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# /settings
# ---------------------------------------------------------------------------

@router.message(Command("settings"))
async def cmd_settings(message: Message, session: AsyncSession) -> None:
    s = await get_db_settings(session)
    areas_str = ", ".join(s.areas) if s.areas else "None configured"

    text = (
        "\u2699\ufe0f <b>Settings</b>\n\n"
        f"<b>Wake time:</b> {s.wake_time}\n"
        f"<b>Wind-down:</b> {s.wind_down_time}\n"
        f"<b>Timezone:</b> {s.timezone}\n"
        f"<b>Notifications:</b> {s.notification_level}\n"
        f"<b>Auto-approve:</b> {s.auto_approve_mode}\n"
        f"<b>Areas:</b> {areas_str}\n"
        f"\n<i>Edit settings via the web UI.</i>"
    )
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# /briefing
# ---------------------------------------------------------------------------

@router.message(Command("briefing"))
async def cmd_briefing(message: Message, session: AsyncSession) -> None:
    from secretary.scheduler.briefings import generate_briefing_text

    text = await generate_briefing_text(session, "daily")
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# /sync
# ---------------------------------------------------------------------------

@router.message(Command("sync"))
async def cmd_sync(message: Message, session: AsyncSession) -> None:
    from secretary.calendar_sync.sync import sync_all_calendars

    await message.answer("\u2699\ufe0f Syncing calendars...")
    try:
        results = await sync_all_calendars(session)
        await session.commit()
    except Exception:
        await message.answer("Calendar sync failed. Check logs for details.")
        return

    if not results:
        await message.answer("No calendar sources configured. Check /settings.")
        return

    lines = ["\u2705 <b>Calendar sync complete</b>\n"]
    for source, stats in results.items():
        if isinstance(stats, dict) and "error" in stats:
            lines.append(f"  <b>{source}:</b> {stats['error']}")
        elif isinstance(stats, dict):
            lines.append(
                f"  <b>{source}:</b> {stats.get('fetched', 0)} fetched, "
                f"{stats.get('created', 0)} created, "
                f"{stats.get('updated', 0)} updated"
            )
        else:
            lines.append(f"  <b>{source}:</b> {stats}")

    await message.answer("\n".join(lines), parse_mode="HTML")
