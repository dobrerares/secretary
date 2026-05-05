"""Tool registry types — the Tool dataclass and ToolCategory enum.

A **Tool** is a registered LLM-callable operation (CONTEXT.md). Each Tool
owns its name, description, Pydantic args schema, executor, category, and
optional domain check. The registry built on these is the single source of
truth — the LLM JSON-Schema, the dispatcher, and the approval policy all
read from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ToolCategory(str, Enum):
    """Tool category — controls how the approval gate handles a tool.

    Vocabulary from CONTEXT.md:

    - **READ**: never gated — always executes. Used for the LLM's reasoning
      loop (e.g. ``list_tasks`` while drafting a proposal); not user-facing.
    - **WRITE**: gated by approval mode. Auto-executes in ``standard`` /
      ``aggressive`` / ``silent``; proposed in ``off``.
    - **DESTRUCTIVE_WRITE**: additional safeguard per PRD §5.1. Proposed in
      ``standard``; auto-executed only in ``aggressive`` / ``silent``.
    """

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE_WRITE = "destructive_write"


# Type aliases for the Tool callables.
ExecuteFn = Callable[[AsyncSession, BaseModel, str], Awaitable[dict]]
"""Tool executor signature: (session, validated_args, batch_id) -> result dict.

The dispatcher wraps the return in ``{"result": ...}``; if execute_fn returns
something already shaped like ``{"error": ...}`` the dispatcher passes it
through unchanged.
"""

DomainCheckFn = Callable[[BaseModel, dict], "str | None"]
"""Domain check signature: (validated_args, context) -> error message or None.

Pydantic owns *structural* validity (types, enums, min_length, gt). A
``domain_check`` is for invariants Pydantic cannot express — typically
runtime-config checks (e.g., ``area_is_known``). The default is a no-op
that always returns None. ``context`` is a dict the caller can stuff with
runtime info the check might need.
"""


def _no_domain_check(_args: BaseModel, _context: dict) -> str | None:
    """Default domain check — accepts everything."""
    return None


@dataclass(frozen=True, slots=True)
class Tool:
    """A registered LLM-callable operation.

    Every Tool carries its own LLM contract (``args_schema``), runtime
    contract (``execute``), approval-policy class (``category``), and
    optional domain invariant (``domain_check``). The registry derived
    from a list of Tool instances is the single source of truth for both
    the LLM JSON-Schema and the runtime dispatcher.
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    execute: ExecuteFn
    category: ToolCategory
    domain_check: DomainCheckFn = field(default=_no_domain_check)
