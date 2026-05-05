"""Tool call dispatcher.

Looks up the named Tool in the registry, validates the LLM-supplied args
against its Pydantic schema, runs its domain check, and calls its execute
function. The Tool registry (``secretary.ai.tools``) is the single source
of truth — adding a tool there makes it dispatchable here automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.tools import BY_NAME

logger = logging.getLogger(__name__)


async def execute_tool(
    session: AsyncSession,
    tool_name: str,
    arguments: dict,
    batch_id: str,
    context: dict[str, Any] | None = None,
) -> dict:
    """Dispatch a tool call. Returns ``{"result": ...}`` or ``{"error": ...}``."""
    tool = BY_NAME.get(tool_name)
    if tool is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        validated = tool.args_schema.model_validate(arguments or {})
        domain_error = tool.domain_check(validated, context or {})
        if domain_error:
            return {"error": domain_error}
        return await tool.execute(session, validated, batch_id)
    except ValidationError as exc:
        return {"error": f"Invalid args for {tool_name}: {exc.errors()}"}
    except Exception as exc:  # noqa: BLE001 — last-resort fence
        logger.exception("Tool execution error for %s: %s", tool_name, exc)
        return {"error": f"Failed to execute {tool_name}: {exc}"}
