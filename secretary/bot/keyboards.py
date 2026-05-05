"""Inline keyboard builders for the Telegram bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def area_keyboard(areas: list[str]) -> InlineKeyboardMarkup:
    """Build area selection keyboard from user's configured areas."""
    builder = InlineKeyboardBuilder()
    for area in areas:
        # Truncate area name to fit callback data limit
        cb = f"area:{area[:50]}"
        builder.button(text=area, callback_data=cb)
    builder.button(text="Skip", callback_data="area:__skip__")
    builder.adjust(2)
    return builder.as_markup()


def priority_keyboard() -> InlineKeyboardMarkup:
    """Build priority selection keyboard."""
    builder = InlineKeyboardBuilder()
    priorities = [
        ("None", "pri:none"),
        ("Low", "pri:low"),
        ("Medium", "pri:medium"),
        ("High", "pri:high"),
        ("Urgent", "pri:urgent"),
    ]
    for label, cb in priorities:
        builder.button(text=label, callback_data=cb)
    builder.button(text="Skip", callback_data="pri:__skip__")
    builder.adjust(3)
    return builder.as_markup()


def confirm_keyboard(action: str, entity_id: int | str) -> InlineKeyboardMarkup:
    """Build Yes/No confirmation keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Yes", callback_data=f"cfm:y:{action}:{entity_id}"),
                InlineKeyboardButton(text="No", callback_data=f"cfm:n:{action}:{entity_id}"),
            ]
        ]
    )


def undo_keyboard(batch_id: str) -> InlineKeyboardMarkup:
    """Build undo button. batch_id is truncated to fit 64-byte limit."""
    short_id = batch_id[:20]
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="\u21a9 Undo", callback_data=f"undo:{short_id}")]]
    )


def task_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Build quick-action keyboard for a task."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2705 Done", callback_data=f"done:{task_id}"),
                InlineKeyboardButton(text="\u270f Edit", callback_data=f"edit:{task_id}"),
                InlineKeyboardButton(text="\ud83d\uddd1 Delete", callback_data=f"del:{task_id}"),
            ]
        ]
    )


def edit_field_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Build field selection keyboard for editing a task."""
    builder = InlineKeyboardBuilder()
    fields = [
        ("Title", f"edf:title:{task_id}"),
        ("Area", f"edf:area:{task_id}"),
        ("Priority", f"edf:pri:{task_id}"),
        ("Due date", f"edf:due:{task_id}"),
        ("Description", f"edf:desc:{task_id}"),
        ("Cancel", f"edf:cancel:{task_id}"),
    ]
    for label, cb in fields:
        builder.button(text=label, callback_data=cb)
    builder.adjust(3)
    return builder.as_markup()


def confirm_create_task_keyboard() -> InlineKeyboardMarkup:
    """Confirm or cancel task creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2705 Create", callback_data="tcr:yes"),
                InlineKeyboardButton(text="\u274c Cancel", callback_data="tcr:no"),
            ]
        ]
    )


def confirm_create_event_keyboard() -> InlineKeyboardMarkup:
    """Confirm or cancel event creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2705 Create", callback_data="ecr:yes"),
                InlineKeyboardButton(text="\u274c Cancel", callback_data="ecr:no"),
            ]
        ]
    )
