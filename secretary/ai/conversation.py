"""Main conversation manager -- orchestrates LLM calls, tool execution, and approval flow."""

import json
import logging
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.client import LLMClient
from secretary.ai.executor import execute_tool
from secretary.ai.system_prompt import render_system_prompt
from secretary.ai.tools import TOOL_NAMES, TOOLS
from secretary.ai.validation import area_is_known, is_destructive
from secretary.config.settings import settings as app_settings
from secretary.core.schemas import (
    EventCreateArgs,
    EventDeleteArgs,
    EventUpdateArgs,
    GetBriefingArgs,
    ListEventsArgs,
    ListTasksArgs,
    ReadSettingsArgs,
    TaskCompleteArgs,
    TaskCreateArgs,
    TaskDeleteArgs,
    TaskUpdateArgs,
    UpdateMemoryArgs,
)
from secretary.core.settings import get_settings
from secretary.db.models import ChatMessage

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
DEFAULT_HISTORY_LIMIT = 20
READ_ONLY_TOOLS = {"list_tasks", "list_events", "get_briefing", "read_settings"}

# Per-tool Pydantic schema dispatcher. Issue #3 will replace this with a
# proper Tool registry; for now this maps each tool name to the schema that
# validates the structural shape of its `args` payload.
_TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "create_task": TaskCreateArgs,
    "update_task": TaskUpdateArgs,
    "complete_task": TaskCompleteArgs,
    "delete_task": TaskDeleteArgs,
    "list_tasks": ListTasksArgs,
    "create_event": EventCreateArgs,
    "update_event": EventUpdateArgs,
    "delete_event": EventDeleteArgs,
    "list_events": ListEventsArgs,
    "get_briefing": GetBriefingArgs,
    "read_settings": ReadSettingsArgs,
    "update_memory": UpdateMemoryArgs,
}

# Tool args fields that carry an area string -- checked against runtime areas
# (Pydantic cannot validate this since user areas are runtime config).
_AREA_BEARING_TOOLS = {
    "create_task",
    "update_task",
    "create_event",
    "update_event",
    "list_tasks",
    "list_events",
}


def _args_are_valid(tool: str, args: dict, user_areas: list[str]) -> bool:
    """Return True if `args` validates against `tool`'s Pydantic schema and
    references a known area (when applicable).
    """
    schema = _TOOL_ARG_SCHEMAS.get(tool)
    if schema is None:
        # Unknown tool -- not safe to auto-execute.
        return False
    try:
        schema.model_validate(args or {})
    except ValidationError:
        return False
    if tool in _AREA_BEARING_TOOLS:
        if not area_is_known((args or {}).get("area"), user_areas):
            return False
    return True


@dataclass
class ConversationResult:
    """Returned by process_message with the AI's text and any pending proposals."""

    response_text: str
    proposed_actions: list[dict] = field(default_factory=list)
    executed_actions: list[dict] = field(default_factory=list)


async def process_message(session: AsyncSession, user_text: str) -> ConversationResult:
    """Process a single user message through the full AI pipeline.

    Steps:
      1. Load settings
      2. Load recent chat history
      3. Render system prompt
      4. Build messages array
      5-9. LLM call loop with tool execution
      10. Persist messages
      11. Return result
    """
    # 1. Load user settings
    user_settings = await get_settings(session)

    # 2. Load recent chat history
    history_limit = getattr(user_settings, "ai_context_messages", DEFAULT_HISTORY_LIMIT) or DEFAULT_HISTORY_LIMIT
    history_messages = await _load_chat_history(session, limit=history_limit)

    # 3. Render system prompt
    system_prompt = render_system_prompt(user_settings)

    # 4. Build messages array
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_text})

    # Track new messages to persist later
    new_messages: list[dict] = [{"role": "user", "content": user_text}]

    # Determine auto-approve behavior
    auto_mode = user_settings.auto_approve_mode  # off | standard | aggressive | silent
    known_areas: list[str] = list(user_settings.areas) if isinstance(user_settings.areas, list) else []

    # Single batch_id for all actions from this user message
    batch_id = str(uuid.uuid4())

    # Collect proposed actions that need approval
    proposed_actions: list[dict] = []

    # Collect actions that were auto-executed (for status reporting)
    executed_actions: list[dict] = []

    # Collect the final assistant text
    final_text = ""

    # Create LLM client
    client = LLMClient(model=app_settings.llm_model, api_key=app_settings.llm_api_key)

    # 5-9. LLM call loop
    for iteration in range(MAX_TOOL_ITERATIONS):
        response = await client.chat(messages, tools=TOOLS)

        choice = response["choices"][0]
        assistant_msg = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        # Capture assistant text if present
        content = assistant_msg.get("content") or ""
        tool_calls = assistant_msg.get("tool_calls") or []

        # Build the message dict as the API expects it
        assistant_message_dict: dict = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_message_dict["tool_calls"] = tool_calls
        messages.append(assistant_message_dict)

        # Record for persistence
        new_messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        })

        if not tool_calls:
            # No tool calls -- LLM is done
            final_text = content
            break

        # Process each tool call
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            call_id = tc.get("id", str(uuid.uuid4()))

            # Parse arguments
            raw_args = func.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                arguments = {}
                logger.warning("Failed to parse tool call arguments: %s", raw_args)

            if tool_name not in TOOL_NAMES:
                # Unknown tool -- return error to the LLM
                tool_result = {"error": f"Unknown tool: {tool_name}"}
                tool_result_str = json.dumps(tool_result)
                messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_result_str})
                new_messages.append({
                    "role": "tool",
                    "content": tool_result_str,
                    "tool_results": {"call_id": call_id, "result": tool_result},
                })
                continue

            action = {"tool": tool_name, "args": arguments, "call_id": call_id}

            # Decide: execute now or propose for approval
            should_execute = _should_auto_execute(action, auto_mode, known_areas)

            if should_execute:
                result = await execute_tool(session, tool_name, arguments, batch_id)
                tool_result_str = json.dumps(result, default=str)
                messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_result_str})
                new_messages.append({
                    "role": "tool",
                    "content": tool_result_str,
                    "tool_results": {"call_id": call_id, "result": result},
                })
                # Track auto-executed mutating actions for status reporting
                if tool_name not in READ_ONLY_TOOLS:
                    executed_actions.append({
                        "tool": tool_name,
                        "args": arguments,
                        "batch_id": batch_id,
                    })
            else:
                # Store as proposed -- give LLM a note that approval is needed
                proposed_actions.append(action)
                pending_note = json.dumps({
                    "status": "pending_approval",
                    "tool": tool_name,
                    "message": "This action requires user approval before execution.",
                })
                messages.append({"role": "tool", "tool_call_id": call_id, "content": pending_note})
                new_messages.append({
                    "role": "tool",
                    "content": pending_note,
                    "tool_results": {"call_id": call_id, "status": "pending_approval"},
                })

        # If the LLM stopped (no more tool calls expected), capture any trailing text
        if finish_reason == "stop":
            final_text = content
            break

        # Otherwise loop back for the LLM to continue after seeing tool results

    else:
        # Exhausted max iterations -- use whatever text we have
        if not final_text:
            final_text = content  # type: ignore[possibly-undefined]

    # 10. Persist all new messages to ChatMessage table
    await _save_messages(session, new_messages)

    # 11. Return result
    return ConversationResult(
        response_text=final_text,
        proposed_actions=proposed_actions,
        executed_actions=executed_actions,
    )


def _should_auto_execute(action: dict, auto_mode: str, areas: list[str]) -> bool:
    """Decide whether a tool call should be executed immediately.

    Rules:
    - "off": nothing auto-executes (except read-only)
    - "standard": non-destructive + validation passes => execute; deletes go to review
    - "aggressive": everything that passes validation, INCLUDING destructive
    - "silent": same as aggressive
    - Read-only tools (list_tasks, list_events, get_briefing, read_settings)
      always auto-execute regardless of mode, since they don't mutate data
    """
    tool = action.get("tool", "")
    args = action.get("args") or {}

    # Read-only tools always execute
    if tool in READ_ONLY_TOOLS:
        return True

    if auto_mode == "off":
        return False

    if auto_mode in ("aggressive", "silent"):
        # Auto-approve everything that passes validation, including destructive
        return _args_are_valid(tool, args, areas)

    # "standard" mode: destructive actions go to review
    if is_destructive(tool):
        return False

    # For standard: validate then execute
    return _args_are_valid(tool, args, areas)


async def _load_chat_history(session: AsyncSession, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict]:
    """Load recent chat messages and reconstruct the messages array."""
    result = await session.execute(
        select(ChatMessage)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(reversed(result.scalars().all()))

    messages: list[dict] = []
    for row in rows:
        msg: dict = {"role": row.role, "content": row.content or ""}
        if row.tool_calls:
            msg["tool_calls"] = row.tool_calls
        if row.role == "tool" and row.tool_results:
            # Reconstruct tool_call_id from stored results
            results_data = row.tool_results
            if isinstance(results_data, dict) and "call_id" in results_data:
                msg["tool_call_id"] = results_data["call_id"]
        messages.append(msg)

    return messages


async def _save_messages(session: AsyncSession, new_messages: list[dict]) -> None:
    """Persist new messages to the ChatMessage table."""
    for msg in new_messages:
        role = msg["role"]
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        tool_results = msg.get("tool_results")

        chat_msg = ChatMessage(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )
        session.add(chat_msg)

    await session.flush()
