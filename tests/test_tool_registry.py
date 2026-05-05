"""Tests for the Tool registry (`secretary.ai.tools`).

A Tool is a registered LLM-callable operation: it owns its name, description,
Pydantic args schema, executor, category, and optional domain check (per
CONTEXT.md). The registry is the single source of truth — the LLM
JSON-Schema, the dispatcher, and the approval policy all read from it.
"""

import dataclasses
import uuid

import pytest
from pydantic import BaseModel


def batch() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def test_public_api_is_importable():
    from secretary.ai.tools import (
        BY_NAME,
        TOOLS,
        Tool,
        ToolCategory,
        llm_schema,
    )

    assert isinstance(TOOLS, list)
    assert isinstance(BY_NAME, dict)
    assert callable(llm_schema)
    assert Tool is not None
    assert ToolCategory is not None


def test_tools_is_list_of_tool_instances():
    from secretary.ai.tools import TOOLS, Tool

    assert len(TOOLS) > 0
    for tool in TOOLS:
        assert isinstance(tool, Tool)


def test_all_twelve_tools_are_registered():
    from secretary.ai.tools import BY_NAME

    expected = {
        "create_task",
        "update_task",
        "complete_task",
        "delete_task",
        "list_tasks",
        "create_event",
        "update_event",
        "delete_event",
        "list_events",
        "get_briefing",
        "read_settings",
        "update_memory",
    }
    assert set(BY_NAME.keys()) == expected


def test_by_name_indexes_tools():
    from secretary.ai.tools import BY_NAME, TOOLS

    assert len(BY_NAME) == len(TOOLS)
    for tool in TOOLS:
        assert BY_NAME[tool.name] is tool


# ---------------------------------------------------------------------------
# Tool dataclass shape
# ---------------------------------------------------------------------------


def test_tool_is_frozen_dataclass():
    from secretary.ai.tools import BY_NAME, Tool

    assert dataclasses.is_dataclass(Tool)
    sample = BY_NAME["create_task"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        sample.name = "mutated"


def test_tool_has_required_fields():
    from secretary.ai.tools import BY_NAME

    sample = BY_NAME["create_task"]
    assert isinstance(sample.name, str)
    assert isinstance(sample.description, str)
    # args_schema is a Pydantic model class
    assert isinstance(sample.args_schema, type)
    assert issubclass(sample.args_schema, BaseModel)
    assert callable(sample.execute)
    assert sample.category is not None
    assert callable(sample.domain_check)


# ---------------------------------------------------------------------------
# Tool category mapping (CONTEXT.md vocabulary)
# ---------------------------------------------------------------------------


def test_read_only_tools_have_read_category():
    from secretary.ai.tools import BY_NAME, ToolCategory

    for name in ("list_tasks", "list_events", "get_briefing", "read_settings"):
        assert BY_NAME[name].category == ToolCategory.READ


def test_write_tools_have_write_category():
    from secretary.ai.tools import BY_NAME, ToolCategory

    for name in (
        "create_task",
        "update_task",
        "complete_task",
        "create_event",
        "update_event",
        "update_memory",
    ):
        assert BY_NAME[name].category == ToolCategory.WRITE


def test_destructive_tools_have_destructive_write_category():
    from secretary.ai.tools import BY_NAME, ToolCategory

    for name in ("delete_task", "delete_event"):
        assert BY_NAME[name].category == ToolCategory.DESTRUCTIVE_WRITE


# ---------------------------------------------------------------------------
# llm_schema() — what we hand to LiteLLM
# ---------------------------------------------------------------------------


def test_llm_schema_returns_list_of_function_dicts():
    from secretary.ai.tools import TOOLS, llm_schema

    schema = llm_schema()
    assert isinstance(schema, list)
    assert len(schema) == len(TOOLS)

    for entry in schema:
        assert entry["type"] == "function"
        assert "function" in entry
        fn = entry["function"]
        assert isinstance(fn["name"], str)
        assert isinstance(fn["description"], str)
        assert "parameters" in fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert isinstance(params.get("required", []), list)


def test_llm_schema_create_task_required_is_title_only():
    """create_task must require exactly `title` — same contract the old
    static schema exposed."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    create_task = next(e for e in schema if e["function"]["name"] == "create_task")
    params = create_task["function"]["parameters"]
    assert params["required"] == ["title"]


def test_llm_schema_priority_field_has_enum():
    """Literal[...] -> enum should round-trip through the adapter."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    create_task = next(e for e in schema if e["function"]["name"] == "create_task")
    priority_prop = create_task["function"]["parameters"]["properties"]["priority"]
    # enum from Literal["none","low","medium","high","urgent"]
    assert "enum" in priority_prop
    assert set(priority_prop["enum"]) == {"none", "low", "medium", "high", "urgent"}


def test_llm_schema_get_briefing_type_has_enum():
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    get_briefing = next(e for e in schema if e["function"]["name"] == "get_briefing")
    type_prop = get_briefing["function"]["parameters"]["properties"]["type"]
    assert "enum" in type_prop
    assert set(type_prop["enum"]) == {"daily", "weekly"}


def test_llm_schema_update_memory_fact_has_min_length():
    """Field(min_length=1) on a string must surface as `minLength: 1`."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    update_memory = next(e for e in schema if e["function"]["name"] == "update_memory")
    fact_prop = update_memory["function"]["parameters"]["properties"]["fact"]
    assert fact_prop.get("type") == "string"
    assert fact_prop.get("minLength") == 1


def test_llm_schema_delete_task_id_is_positive_integer():
    """Field(gt=0) must surface as `exclusiveMinimum: 0`."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    delete_task = next(e for e in schema if e["function"]["name"] == "delete_task")
    id_prop = delete_task["function"]["parameters"]["properties"]["task_id"]
    assert id_prop.get("type") == "integer"
    assert id_prop.get("exclusiveMinimum") == 0


def test_llm_schema_optional_field_not_in_required():
    """Optional / `X | None` fields with defaults must not appear in `required`."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    create_task = next(e for e in schema if e["function"]["name"] == "create_task")
    required = set(create_task["function"]["parameters"].get("required", []))
    assert "description" not in required
    assert "area" not in required


def test_llm_schema_optional_string_has_string_type():
    """`X | None` should normalise to a single type, not dump anyOf."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    create_task = next(e for e in schema if e["function"]["name"] == "create_task")
    desc_prop = create_task["function"]["parameters"]["properties"]["description"]
    # The adapter should fold X|None into a plain type — OpenAI doesn't
    # need the anyOf-with-null shape.
    assert desc_prop.get("type") == "string"


def test_llm_schema_datetime_field_marked_as_date_time():
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    create_task = next(e for e in schema if e["function"]["name"] == "create_task")
    due_at_prop = create_task["function"]["parameters"]["properties"]["due_at"]
    assert due_at_prop.get("type") == "string"
    assert due_at_prop.get("format") == "date-time"


def test_llm_schema_list_of_strings_has_array_with_items():
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    create_task = next(e for e in schema if e["function"]["name"] == "create_task")
    tags_prop = create_task["function"]["parameters"]["properties"]["tags"]
    assert tags_prop.get("type") == "array"
    assert tags_prop["items"]["type"] == "string"


def test_llm_schema_strips_pydantic_title_field():
    """OpenAI doesn't need the `title` field Pydantic adds — keep schemas
    lean and on-purpose."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    for entry in schema:
        params = entry["function"]["parameters"]
        assert "title" not in params
        for prop in params.get("properties", {}).values():
            assert "title" not in prop


def test_llm_schema_field_descriptions_pass_through():
    """Pydantic Field(description=...) descriptions, when present, should
    surface in the generated schema."""
    from secretary.ai.tools import llm_schema

    schema = llm_schema()
    create_task = next(e for e in schema if e["function"]["name"] == "create_task")
    fn = create_task["function"]
    # Tool-level description must be present.
    assert fn["description"]
    assert isinstance(fn["description"], str)


# ---------------------------------------------------------------------------
# execute_tool dispatcher behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_unknown_returns_error(session):
    from secretary.ai.executor import execute_tool

    result = await execute_tool(session, "no_such_tool", {}, batch())
    assert "error" in result
    assert "result" not in result


@pytest.mark.asyncio
async def test_execute_tool_invalid_args_returns_error(session):
    """Structurally-bad args (delete_task with task_id=0) must come back as
    an error — Pydantic's `gt=0` constraint must gate execution."""
    from secretary.ai.executor import execute_tool

    result = await execute_tool(session, "delete_task", {"task_id": 0}, batch())
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_tool_missing_required_args_returns_error(session):
    from secretary.ai.executor import execute_tool

    result = await execute_tool(session, "create_task", {}, batch())  # no title
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_tool_create_task_returns_snapshot(session):
    """Smoke test: create_task with valid args persists a Task and returns
    its Snapshot under {"result": ...}."""
    from secretary.ai.executor import execute_tool
    from secretary.core.tasks import get_task

    result = await execute_tool(
        session,
        "create_task",
        {"title": "Smoke test", "priority": "high"},
        batch(),
    )
    assert "result" in result
    snap = result["result"]
    assert snap["title"] == "Smoke test"
    assert snap["priority"] == "high"
    # Confirm it actually landed in the DB
    persisted = await get_task(session, snap["id"])
    assert persisted is not None
    assert persisted.title == "Smoke test"


@pytest.mark.asyncio
async def test_execute_tool_delete_task_not_found_returns_error(session):
    from secretary.ai.executor import execute_tool

    result = await execute_tool(session, "delete_task", {"task_id": 999}, batch())
    assert "error" in result
