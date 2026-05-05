"""Domain helpers for the auto-approve gate.

Pydantic owns the structural validity of tool args (see core/schemas.py).
The Tool registry (see secretary/ai/tools) owns each tool's category. This
module only carries domain checks neither of those can make at construction
time — most importantly whether an area is one the user has configured.
"""

from secretary.ai.tools import BY_NAME, ToolCategory


def is_destructive(tool: str) -> bool:
    """Return True if the named tool destroys data.

    Thin wrapper over the Tool registry's ``ToolCategory.DESTRUCTIVE_WRITE``
    — kept for callers that want a tool-name-string predicate. Unknown tool
    names are treated as non-destructive (the dispatcher will reject them
    independently).
    """
    spec = BY_NAME.get(tool)
    return spec is not None and spec.category == ToolCategory.DESTRUCTIVE_WRITE


def area_is_known(area: str | None, user_areas: list[str]) -> bool:
    """Return True if `area` is one the user has configured.

    Pydantic cannot enforce this -- the user's areas are runtime config, not
    a static enum. Conventions:
      - `area is None` (no area set) is always allowed.
      - If the user has not configured any areas, accept any string.
      - Otherwise the area must be in `user_areas`.
    """
    if area is None:
        return True
    if not user_areas:
        return True
    return area in user_areas
