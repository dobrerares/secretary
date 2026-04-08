"""FSM state groups for multi-step bot commands."""

from aiogram.fsm.state import State, StatesGroup


class AddTaskStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_area = State()
    waiting_for_priority = State()
    waiting_for_due = State()
    waiting_for_confirm = State()


class AddEventStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_start = State()
    waiting_for_end = State()
    waiting_for_confirm = State()


class EditTaskStates(StatesGroup):
    waiting_for_field = State()
    waiting_for_value = State()


class OnboardStates(StatesGroup):
    waiting_for_areas = State()
