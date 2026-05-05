"""tighten action_log.entity_type CHECK to ('task', 'event')

Subtasks and Tags are children that ride inside their Root entity's
Snapshot — they are not Root entities and therefore never appear as a
standalone Action target. InboxItems are workflow staging, also not a
Root entity. The CHECK constraint reflects this invariant.

Revision ID: be46ce80f932
Revises: 613ef3889d69
Create Date: 2026-05-05 04:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "be46ce80f932"
down_revision: Union[str, Sequence[str], None] = "613ef3889d69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rebuild(check_clause: str) -> None:
    """Rebuild the action_log table with a different entity_type CHECK.

    The original schema declared the CHECK inline without a name, so we
    can't drop it by name. We rebuild the table from scratch via the
    standard SQLite recipe (rename → create → copy → drop)."""
    op.execute("ALTER TABLE action_log RENAME TO action_log_old")

    op.create_table(
        "action_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("action_type", sa.String(length=8), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("is_undone", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("action_type IN ('create', 'update', 'delete')"),
        sa.CheckConstraint(check_clause, name="ck_action_log_entity_type"),
    )

    op.execute(
        "INSERT INTO action_log "
        "(id, action_type, entity_type, entity_id, before_state, after_state, "
        " batch_id, is_undone, created_at, expires_at) "
        "SELECT id, action_type, entity_type, entity_id, before_state, after_state, "
        "       batch_id, is_undone, created_at, expires_at "
        "FROM action_log_old "
        f"WHERE entity_type IN ({_in_clause(check_clause)})"
    )

    op.execute("DROP TABLE action_log_old")

    op.create_index("ix_action_log_batch_id", "action_log", ["batch_id"])
    op.create_index("ix_action_log_entity", "action_log", ["entity_type", "entity_id"])
    op.create_index("ix_action_log_undone_created", "action_log", ["is_undone", "created_at"])


def _in_clause(check_clause: str) -> str:
    """Extract the IN-list values from a CHECK clause like
    `entity_type IN ('task', 'event')` so we can filter the data copy."""
    start = check_clause.index("(") + 1
    end = check_clause.rindex(")")
    return check_clause[start:end]


def upgrade() -> None:
    """Tighten entity_type CHECK to `IN ('task', 'event')`. Legacy rows
    referencing 'subtask' or 'inbox_item' are dropped — they were never
    used by the Action seam."""
    _rebuild("entity_type IN ('task', 'event')")


def downgrade() -> None:
    """Widen entity_type CHECK back to the original four values."""
    _rebuild("entity_type IN ('task', 'event', 'inbox_item', 'subtask')")
