"""Tool registry — single source of truth for the LLM contract and runtime.

A **Tool** (CONTEXT.md) bundles its name, description, Pydantic args
schema, executor, category, and optional domain check into one immutable
record. The list of Tool instances drives:

- ``llm_schema()`` — the JSON-Schema list LiteLLM consumes
- ``BY_NAME`` — the lookup the dispatcher uses
- ``ToolCategory`` — what the approval gate reads to decide auto-execute

Three modules group the twelve tools by surface area:

- ``task_tools`` — five Tools over Task root entities
- ``event_tools`` — four Tools over Event root entities
- ``system_tools`` — three Tools that aren't tied to a Root entity
"""

from secretary.ai.tools._schema import pydantic_to_openai_schema
from secretary.ai.tools._types import Tool, ToolCategory
from secretary.ai.tools.event_tools import EVENT_TOOLS
from secretary.ai.tools.system_tools import SYSTEM_TOOLS
from secretary.ai.tools.task_tools import TASK_TOOLS

TOOLS: list[Tool] = [*TASK_TOOLS, *EVENT_TOOLS, *SYSTEM_TOOLS]

BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


# Built once at import time — TOOLS is immutable for the process lifetime
# and the LLM call loop reads this every iteration.
_LLM_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": pydantic_to_openai_schema(tool.args_schema),
        },
    }
    for tool in TOOLS
]


def llm_schema() -> list[dict]:
    """Return the OpenAI / LiteLLM-shaped tool list from the registry.

    Each entry is::

        {"type": "function",
         "function": {"name": ..., "description": ..., "parameters": {...}}}
    """
    return _LLM_SCHEMA


__all__ = [
    "BY_NAME",
    "TOOLS",
    "Tool",
    "ToolCategory",
    "llm_schema",
]
