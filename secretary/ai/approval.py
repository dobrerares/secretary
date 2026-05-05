"""Approval policy — decide whether a Tool call auto-executes or is proposed.

The approval gate from PRD §5.1 is a pure function of two inputs: the Tool's
category (READ / WRITE / DESTRUCTIVE_WRITE) and the user's auto-approve mode
(off / standard / aggressive / silent). This module encodes that matrix and
returns a **Decision** (CONTEXT.md): ``Execute()`` | ``ExecuteSilent()`` |
``Propose(reason)``.

The discriminated union lets callers ``match`` on the result cleanly:

    decision = decide(BY_NAME[tool_name].category, settings.auto_approve_mode)
    match decision:
        case Execute() | ExecuteSilent():
            ...  # auto-execute (silent variant skips user-facing surfacing)
        case Propose(reason):
            ...  # add `reason` to the suggestion card

The matrix
----------

==================  ===  ========  ==========  ==========
                    off  standard  aggressive  silent
==================  ===  ========  ==========  ==========
READ                ES   ES        ES          ES
WRITE               P    E         E           ES
DESTRUCTIVE_WRITE   P    P         E           ES
==================  ===  ========  ==========  ==========

Legend: E = Execute, ES = ExecuteSilent, P = Propose.

READ tools are never gated — they back the LLM's reasoning loop and aren't
user-facing, so they always run silently. ``silent`` mode auto-executes
everything but suppresses the executed-action surfacing. ``aggressive`` runs
destructive tools without approval; ``standard`` keeps the destructive
safeguard.
"""

from __future__ import annotations

from dataclasses import dataclass

from secretary.ai.tools import ToolCategory
from secretary.core.schemas import AutoApproveMode


@dataclass(frozen=True)
class Execute:
    """Run the Tool now and surface it to the user as an executed action."""


@dataclass(frozen=True)
class ExecuteSilent:
    """Run the Tool now without surfacing it as a user-facing executed action.

    Used for READ tools (the LLM's reasoning loop) and for ``silent`` mode,
    where the user has opted out of seeing every executed action.
    """


@dataclass(frozen=True, slots=True)
class Propose:
    """Defer execution and surface the Tool call on a suggestion card.

    ``reason`` is shown to the user so they understand why approval was
    required (auto-approve is off, destructive safeguard, etc.).
    """

    reason: str


Decision = Execute | ExecuteSilent | Propose


# Reason strings for the Propose paths — kept short and consistent so the
# suggestion card stays scannable.
_REASON_OFF = "Auto-approve is off. Review and approve to execute."
_REASON_DESTRUCTIVE_STANDARD = "Destructive action — requires approval in standard mode."


def decide(category: ToolCategory, mode: AutoApproveMode) -> Decision:
    """Return the approval Decision for a Tool of ``category`` under ``mode``.

    Pure function: same inputs always produce the same Decision. Implements
    the PRD §5.1 matrix. See module docstring for the table.
    """
    # READ never gated.
    if category == ToolCategory.READ:
        return ExecuteSilent()

    # silent mode auto-executes everything without surfacing.
    if mode == "silent":
        return ExecuteSilent()

    # off mode never auto-executes WRITE / DESTRUCTIVE_WRITE.
    if mode == "off":
        return Propose(reason=_REASON_OFF)

    # WRITE: standard and aggressive auto-execute.
    if category == ToolCategory.WRITE:
        return Execute()

    # DESTRUCTIVE_WRITE: aggressive auto-executes, standard requires approval.
    if mode == "aggressive":
        return Execute()
    return Propose(reason=_REASON_DESTRUCTIVE_STANDARD)
