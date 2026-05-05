"""Conversation pipeline — capture, parse with the LLM, decide, attach.

This module is the parser + decider layer between user-facing controllers
(bot, web, voice) and the Inbox state machine. The flow:

1. ``inbox.capture`` an InboxItem in ``pending``.
2. Run the LLM tool-calling loop, validating each tool call.
3. Per call, consult :func:`secretary.ai.approval.decide` and either
   execute through the dispatcher or stash the call as a Proposed
   action with a ``reason``.
4. Call ``inbox.attach_actions`` to persist the run under the item's
   batch_id, flipping the item to ``processed`` (no Proposed) or
   ``proposed`` (Proposed present).

Controllers receive a :class:`ProcessResult` describing the AI's reply,
the executed actions (for status reports / undo cards), and the freshly
captured InboxItem (which exposes ``proposed_actions`` with stable
``action_id``s for suggestion cards).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.approval import Execute, ExecuteSilent, Propose, decide
from secretary.ai.client import LLMClient
from secretary.ai.executor import execute_tool
from secretary.ai.system_prompt import render_system_prompt
from secretary.ai.tools import BY_NAME, llm_schema
from secretary.config.settings import settings as app_settings
from secretary.core import inbox
from secretary.core.schemas import area_is_known
from secretary.core.settings import get_settings
from secretary.db.models import ChatMessage, InboxItem

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
DEFAULT_HISTORY_LIMIT = 20

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

# Reason shown on the suggestion card when the LLM produced args that
# don't validate. Surfaced via Propose so the user reviews rather than
# auto-executing bogus input.
_REASON_INVALID_ARGS = "Could not validate tool arguments — review before executing."


def _args_are_valid(tool: str, args: dict, user_areas: list[str]) -> bool:
    """Return True if ``args`` validates structurally and references a
    known area when applicable."""
    spec = BY_NAME.get(tool)
    if spec is None:
        return False
    try:
        spec.args_schema.model_validate(args or {})
    except ValidationError:
        return False
    if tool in _AREA_BEARING_TOOLS:
        if not area_is_known((args or {}).get("area"), user_areas):
            return False
    return True


@dataclass
class ProcessResult:
    """Returned by :func:`process_message` to the controllers.

    - ``item`` — the captured :class:`InboxItem`. Its ``proposed_actions``
      already carry stable UUID ``action_id``s for suggestion cards.
    - ``response_text`` — the AI's final user-facing reply.
    - ``executed`` — actions that ran auto-execute. Each entry is
      ``{"tool", "args", "batch_id", "silent"}``; controllers render
      status reports + undo cards from this list (skipping ``silent``
      entries).
    - ``proposed`` — Proposed actions awaiting user approval (a copy
      of ``item.proposed_actions``); kept for convenience.
    """

    item: InboxItem
    response_text: str
    executed: list[dict] = field(default_factory=list)
    proposed: list[dict] = field(default_factory=list)


async def process_message(
    session: AsyncSession,
    user_text: str,
    source: str = "chat",
) -> ProcessResult:
    """Capture, parse with the LLM, decide per tool call, attach the result.

    Steps:
      1. Capture an InboxItem in ``pending``.
      2. Load settings and recent chat history; render the system prompt.
      3. Loop the LLM with tools, validating each call; pre-decide via
         :func:`secretary.ai.approval.decide`.
      4. Auto-execute or stash as Proposed (with the policy ``reason``).
      5. Persist new chat messages.
      6. ``inbox.attach_actions`` to flip the item to ``processed`` or
         ``proposed`` and assign UUID ``action_id``s.
    """
    # 1. Capture an inbox item up front so every downstream branch has
    #    something to attach to.
    item = await inbox.capture(session, raw_text=user_text, source=source)

    user_settings = await get_settings(session)
    history_limit = getattr(user_settings, "ai_context_messages", DEFAULT_HISTORY_LIMIT) or DEFAULT_HISTORY_LIMIT
    history_messages = await _load_chat_history(session, limit=history_limit)
    system_prompt = render_system_prompt(user_settings)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_text})

    new_messages: list[dict] = [{"role": "user", "content": user_text}]

    auto_mode = user_settings.auto_approve_mode
    known_areas: list[str] = list(user_settings.areas) if isinstance(user_settings.areas, list) else []

    # Single batch_id for the whole AI run — attach_actions will record
    # it on the item, and approve_action reuses it later so undo-batch
    # reverts auto-executed and approved actions together.
    batch_id = str(uuid.uuid4())

    proposed: list[dict] = []
    executed: list[dict] = []
    final_text = ""

    client = LLMClient(model=app_settings.llm_model, api_key=app_settings.llm_api_key)

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await client.chat(messages, tools=llm_schema())

        choice = response["choices"][0]
        assistant_msg = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        content = assistant_msg.get("content") or ""
        tool_calls = assistant_msg.get("tool_calls") or []

        assistant_message_dict: dict = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_message_dict["tool_calls"] = tool_calls
        messages.append(assistant_message_dict)
        new_messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls if tool_calls else None,
            }
        )

        if not tool_calls:
            final_text = content
            break

        for tc in tool_calls:
            await _handle_tool_call(
                session=session,
                tc=tc,
                messages=messages,
                new_messages=new_messages,
                executed=executed,
                proposed=proposed,
                batch_id=batch_id,
                auto_mode=auto_mode,
                known_areas=known_areas,
            )

        if finish_reason == "stop":
            final_text = content
            break

    else:  # max iterations exhausted
        if not final_text:
            final_text = content  # type: ignore[possibly-undefined]

    await _save_messages(session, new_messages)

    # 6. Attach results to the inbox item — assigns UUID action_ids and
    #    flips the item's status. From here on the item is the source of
    #    truth for Proposed actions; controllers render from
    #    item.proposed_actions.
    item = await inbox.attach_actions(
        session,
        item,
        executed=executed,
        proposed=proposed,
        batch_id=batch_id,
    )

    return ProcessResult(
        item=item,
        response_text=final_text,
        executed=executed,
        proposed=list(item.proposed_actions or []),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _handle_tool_call(
    *,
    session: AsyncSession,
    tc: dict,
    messages: list[dict],
    new_messages: list[dict],
    executed: list[dict],
    proposed: list[dict],
    batch_id: str,
    auto_mode: str,
    known_areas: list[str],
) -> None:
    """Process a single tool call from the LLM response.

    Decides via :func:`decide` (or forces Propose on invalid args),
    executes through the dispatcher or stashes a Proposed action, and
    threads the result back into the LLM message stream.
    """
    func = tc.get("function", {})
    tool_name = func.get("name", "")
    call_id = tc.get("id", str(uuid.uuid4()))

    raw_args = func.get("arguments", "{}")
    try:
        arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except json.JSONDecodeError:
        arguments = {}
        logger.warning("Failed to parse tool call arguments: %s", raw_args)

    if tool_name not in BY_NAME:
        tool_result = {"error": f"Unknown tool: {tool_name}"}
        tool_result_str = json.dumps(tool_result)
        messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_result_str})
        new_messages.append(
            {
                "role": "tool",
                "content": tool_result_str,
                "tool_results": {"call_id": call_id, "result": tool_result},
            }
        )
        return

    # Decide: invalid args force Propose, otherwise consult the matrix
    # in secretary/ai/approval.py.
    if not _args_are_valid(tool_name, arguments, known_areas):
        decision = Propose(reason=_REASON_INVALID_ARGS)
    else:
        decision = decide(BY_NAME[tool_name].category, auto_mode)

    match decision:
        case Execute() | ExecuteSilent():
            silent = isinstance(decision, ExecuteSilent)
            result = await execute_tool(session, tool_name, arguments, batch_id)
            tool_result_str = json.dumps(result, default=str)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_result_str})
            new_messages.append(
                {
                    "role": "tool",
                    "content": tool_result_str,
                    "tool_results": {"call_id": call_id, "result": result},
                }
            )
            executed.append(
                {
                    "tool": tool_name,
                    "args": arguments,
                    "batch_id": batch_id,
                    "silent": silent,
                    "result": result,
                }
            )
        case Propose(reason=reason):
            proposed.append(
                {
                    "tool": tool_name,
                    "args": arguments,
                    "reason": reason,
                }
            )
            pending_note = json.dumps(
                {
                    "status": "pending_approval",
                    "tool": tool_name,
                    "reason": reason,
                    "message": "This action requires user approval before execution.",
                }
            )
            messages.append({"role": "tool", "tool_call_id": call_id, "content": pending_note})
            new_messages.append(
                {
                    "role": "tool",
                    "content": pending_note,
                    "tool_results": {"call_id": call_id, "status": "pending_approval", "reason": reason},
                }
            )


async def _load_chat_history(session: AsyncSession, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict]:
    """Load recent chat messages and reconstruct the messages array."""
    result = await session.execute(select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(limit))
    rows = list(reversed(result.scalars().all()))

    messages: list[dict] = []
    for row in rows:
        msg: dict = {"role": row.role, "content": row.content or ""}
        if row.tool_calls:
            msg["tool_calls"] = row.tool_calls
        if row.role == "tool" and row.tool_results:
            results_data = row.tool_results
            if isinstance(results_data, dict) and "call_id" in results_data:
                msg["tool_call_id"] = results_data["call_id"]
        messages.append(msg)

    return messages


async def _save_messages(session: AsyncSession, new_messages: list[dict]) -> None:
    """Persist new messages to the ChatMessage table."""
    for msg in new_messages:
        chat_msg = ChatMessage(
            role=msg["role"],
            content=msg.get("content"),
            tool_calls=msg.get("tool_calls"),
            tool_results=msg.get("tool_results"),
        )
        session.add(chat_msg)

    await session.flush()
