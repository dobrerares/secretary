"""Pydantic-to-OpenAI JSON-Schema adapter.

OpenAI / LiteLLM expects each tool entry as::

    {"type": "function", "function": {"name": ..., "description": ...,
                                       "parameters": {...JSON-Schema...}}}

Pydantic's ``model_json_schema()`` is JSON-Schema 2020-12, which OpenAI
mostly accepts — but it adds noise (``title`` on every field) and uses the
``anyOf: [<T>, {"type":"null"}]`` shape for ``X | None`` instead of folding
nullability into the field's optionality. This module strips and reshapes
the Pydantic output into the lean form the LLM contract calls for.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def pydantic_to_openai_schema(args_schema: type[BaseModel]) -> dict[str, Any]:
    """Generate an OpenAI function-calling JSON-Schema from a Pydantic model.

    Returns the ``parameters`` block (the dict OpenAI puts under
    ``function.parameters``). The caller wraps it in the
    ``{"type": "function", "function": {...}}`` envelope.

    Handles:
      - primitive types (str/int/bool) → ``{"type": ...}``
      - ``Literal[...]`` → ``{"type": "string", "enum": [...]}``
      - ``X | None`` / ``Optional[X]`` → folded into a single type, NOT in
        ``required`` (defaults are dropped — the absence of the field in
        ``required`` carries the same information)
      - ``list[T]`` → ``{"type": "array", "items": {...}}``
      - ``datetime`` → ``{"type": "string", "format": "date-time"}``
      - ``Field(description=...)`` → ``description``
      - ``Field(min_length=N, gt=N, ...)`` → ``minLength``, ``exclusiveMinimum``, …

    Pydantic's ``title`` field is dropped (LLMs don't need it).
    Nested ``$defs`` are inlined.
    """
    raw = args_schema.model_json_schema()
    defs = raw.get("$defs", {})

    properties = {}
    for fname, fschema in raw.get("properties", {}).items():
        properties[fname] = _massage_field(fschema, defs)

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(raw.get("required", [])),
    }
    return parameters


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Field-level keys we want to keep. Anything else (defaults, titles, etc.)
# gets dropped — defaults are encoded by absence-from-required and Pydantic's
# own validator at execution time, so the LLM doesn't need to see them.
_KEEP_KEYS = {
    "type",
    "enum",
    "format",
    "description",
    "items",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "pattern",
    "properties",
    "required",
}


def _massage_field(fschema: dict, defs: dict) -> dict:
    """Take one Pydantic-emitted field schema and emit the OpenAI-friendly form."""
    # Resolve $ref into the inlined definition.
    fschema = _resolve_ref(fschema, defs)

    if "anyOf" in fschema:
        # X | None → strip the null branch, lift the remaining branch.
        branches = [b for b in fschema["anyOf"] if b.get("type") != "null"]
        if len(branches) == 1:
            inner = _massage_field(branches[0], defs)
            # Carry through any sibling description from the outer schema.
            for sibling_key in ("description",):
                if sibling_key in fschema and sibling_key not in inner:
                    inner[sibling_key] = fschema[sibling_key]
            return inner
        # Multi-branch unions — keep as-is, but strip noise from each branch.
        return {"anyOf": [_massage_field(b, defs) for b in branches]}

    cleaned: dict[str, Any] = {k: v for k, v in fschema.items() if k in _KEEP_KEYS}

    # Recurse into list items.
    if "items" in cleaned:
        cleaned["items"] = _massage_field(cleaned["items"], defs)

    # Recurse into nested object properties (from $defs).
    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["properties"] = {
            k: _massage_field(v, defs) for k, v in cleaned["properties"].items()
        }

    return cleaned


def _resolve_ref(fschema: dict, defs: dict) -> dict:
    """If ``fschema`` is a ``$ref``, dereference it against ``defs``."""
    ref = fschema.get("$ref")
    if not ref:
        return fschema
    if not ref.startswith("#/$defs/"):
        return fschema
    name = ref.removeprefix("#/$defs/")
    return defs.get(name, fschema)
