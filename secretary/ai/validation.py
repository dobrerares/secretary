"""Domain helpers for the auto-approve gate.

Pydantic owns the structural validity of tool args (see core/schemas.py).
This module only carries domain decisions Pydantic cannot make: which tools
are destructive, and whether an area is one the user has configured.
"""

# Tool calls that destroy data. In standard mode these require explicit
# approval; in aggressive/silent mode they may be auto-approved if their
# args validate.
_DESTRUCTIVE_TOOLS = {"delete_task", "delete_event"}


def is_destructive(tool: str) -> bool:
    """Return True if the named tool destroys data."""
    return tool in _DESTRUCTIVE_TOOLS


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
