"""Tests for the approval policy module (`secretary.ai.approval`).

The approval policy collapses the auto-approve gate from PRD §5.1 into a
pure function: ``decide(category, mode) -> Decision``. ``Decision`` is the
discriminated union from CONTEXT.md: ``Execute()`` | ``ExecuteSilent()`` |
``Propose(reason)``. This module is the single source of truth for whether
a Tool call auto-executes, executes-silently, or surfaces as a proposed
action awaiting user approval.
"""

import dataclasses

import pytest


# ---------------------------------------------------------------------------
# Public API exports
# ---------------------------------------------------------------------------


def test_public_api_is_importable():
    from secretary.ai.approval import (
        Decision,
        Execute,
        ExecuteSilent,
        Propose,
        decide,
    )

    assert Execute is not None
    assert ExecuteSilent is not None
    assert Propose is not None
    assert Decision is not None
    assert callable(decide)


# ---------------------------------------------------------------------------
# Decision variants are frozen dataclasses, pattern-matchable
# ---------------------------------------------------------------------------


def test_execute_is_frozen_dataclass():
    from secretary.ai.approval import Execute

    assert dataclasses.is_dataclass(Execute)
    inst = Execute()
    with pytest.raises(dataclasses.FrozenInstanceError):
        inst.foo = "bar"  # type: ignore[attr-defined]


def test_execute_silent_is_frozen_dataclass():
    from secretary.ai.approval import ExecuteSilent

    assert dataclasses.is_dataclass(ExecuteSilent)
    inst = ExecuteSilent()
    with pytest.raises(dataclasses.FrozenInstanceError):
        inst.foo = "bar"  # type: ignore[attr-defined]


def test_propose_is_frozen_dataclass_with_reason():
    from secretary.ai.approval import Propose

    assert dataclasses.is_dataclass(Propose)
    inst = Propose(reason="why")
    assert inst.reason == "why"
    with pytest.raises(dataclasses.FrozenInstanceError):
        inst.reason = "different"


def test_decision_variants_are_pattern_matchable():
    """Callers should be able to ``match`` on a Decision and route cleanly."""
    from secretary.ai.approval import Decision, Execute, ExecuteSilent, Propose

    def label(d: Decision) -> str:
        match d:
            case Execute():
                return "execute"
            case ExecuteSilent():
                return "silent"
            case Propose(reason=r):
                return f"propose:{r}"

    assert label(Execute()) == "execute"
    assert label(ExecuteSilent()) == "silent"
    assert label(Propose(reason="approval needed")) == "propose:approval needed"


# ---------------------------------------------------------------------------
# decide(category, mode) — full 12-cell matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category_name,mode,expected_variant",
    [
        # READ → always ExecuteSilent (never gated, not surfaced to user)
        ("READ", "off", "ExecuteSilent"),
        ("READ", "standard", "ExecuteSilent"),
        ("READ", "aggressive", "ExecuteSilent"),
        ("READ", "silent", "ExecuteSilent"),
        # WRITE: off → Propose; standard / aggressive → Execute; silent → ExecuteSilent
        ("WRITE", "off", "Propose"),
        ("WRITE", "standard", "Execute"),
        ("WRITE", "aggressive", "Execute"),
        ("WRITE", "silent", "ExecuteSilent"),
        # DESTRUCTIVE_WRITE: off / standard → Propose; aggressive → Execute; silent → ExecuteSilent
        ("DESTRUCTIVE_WRITE", "off", "Propose"),
        ("DESTRUCTIVE_WRITE", "standard", "Propose"),
        ("DESTRUCTIVE_WRITE", "aggressive", "Execute"),
        ("DESTRUCTIVE_WRITE", "silent", "ExecuteSilent"),
    ],
)
def test_decide_matrix(category_name, mode, expected_variant):
    from secretary.ai.approval import Execute, ExecuteSilent, Propose, decide
    from secretary.ai.tools import ToolCategory

    variant_map = {
        "Execute": Execute,
        "ExecuteSilent": ExecuteSilent,
        "Propose": Propose,
    }
    category = ToolCategory[category_name]
    expected_cls = variant_map[expected_variant]

    result = decide(category, mode)

    assert isinstance(result, expected_cls), (
        f"decide({category_name}, {mode!r}) returned {type(result).__name__}, expected {expected_variant}"
    )


# ---------------------------------------------------------------------------
# Propose carries a non-empty human-readable reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category_name,mode",
    [
        ("WRITE", "off"),
        ("DESTRUCTIVE_WRITE", "off"),
        ("DESTRUCTIVE_WRITE", "standard"),
    ],
)
def test_propose_carries_non_empty_reason(category_name, mode):
    from secretary.ai.approval import Propose, decide
    from secretary.ai.tools import ToolCategory

    result = decide(ToolCategory[category_name], mode)

    assert isinstance(result, Propose)
    assert isinstance(result.reason, str)
    assert result.reason.strip() != ""


def test_propose_reason_for_destructive_in_standard_mentions_destructive():
    """The standard-mode safeguard reason should hint at WHY (it's destructive)
    so the suggestion card is informative."""
    from secretary.ai.approval import Propose, decide
    from secretary.ai.tools import ToolCategory

    result = decide(ToolCategory.DESTRUCTIVE_WRITE, "standard")

    assert isinstance(result, Propose)
    assert "destructive" in result.reason.lower()


def test_propose_reason_for_off_mode_mentions_auto_approve():
    """The off-mode reason should reference auto-approve being off."""
    from secretary.ai.approval import Propose, decide
    from secretary.ai.tools import ToolCategory

    result = decide(ToolCategory.WRITE, "off")

    assert isinstance(result, Propose)
    assert "auto-approve" in result.reason.lower() or "off" in result.reason.lower()
