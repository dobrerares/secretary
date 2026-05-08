# Domain Glossary

The vocabulary that engineering and product agree to use. Any agent skill writing about this codebase should pick its words from here.

## Action

A logged, reversible operation on a root entity. Each Action captures the entity's snapshot before and/or after the operation, plus a `batch_id` that groups it with related Actions. Actions expire after `undo_expiry_minutes` (default 60) and can be undone individually or as a batch.

The PRD uses "action" loosely (any write); here it's tightened. Not every DB write is an Action — only operations on root entities go through the action seam. An inbox item flipping from `pending` to `rejected` is **not** an Action (inbox state is workflow staging, not user data).

## Root entity

An entity with its own Action seam. Today: **Task** and **Event**. Children (Subtasks, Tags) do not produce their own Actions — they ride inside their root's snapshot.

## Snapshot

The canonical record of a root entity — one shape, two jobs. `ActionLog` stores it as `before_state` / `after_state` for undo; the AI tool layer and any future API client receive it as the entity's outward-facing form ("the card").

We chose one card per entity type (rather than separate "snapshot" and "API result" formats) because the current Task/Event models have no internal-only state the LLM shouldn't see. If divergence pressure ever appears, the seam splits.

## Batch

A UUID grouping Actions that should undo together. One inbox-item approval that produces three Tasks and one Event yields four Actions sharing a `batch_id`; the user undoes them as one unit.

## Tool

A registered LLM-callable operation. Each Tool owns its name, description (LLM-facing), Pydantic args schema, executor function, category, and optional domain check. The Tool registry is the single source of truth — the LLM JSON-Schema, the dispatcher, and the approval policy all read from it.

PRD §7.1 lists tools as a table; the Tool concept here is the runtime equivalent.

## Tool category

`READ` | `WRITE` | `DESTRUCTIVE_WRITE`. Controls how the approval gate handles a tool:

- **READ**: never gated — always executes. Used for the LLM's reasoning loop (e.g. `list_tasks` while drafting a proposal); not user-facing.
- **WRITE**: gated by approval mode. Auto-executes in `standard` / `aggressive` / `silent`; proposed in `off`.
- **DESTRUCTIVE_WRITE**: additional safeguard per PRD §5.1. Proposed in `standard`; auto-executed only in `aggressive` / `silent`.

## Decision

The approval policy's output: `Execute()` | `ExecuteSilent()` | `Propose(reason: str)`. The reason is shown on the suggestion card so the user understands why a given action wasn't auto-approved.

## Proposed action

A single tool call awaiting user decision, identified by a stable UUID `action_id`. Stored on its parent inbox item's `proposed_actions` field. Lifecycle: `pending → approved | rejected`. When all proposed actions for an inbox item are decided, the item auto-resolves to `processed` (or `rejected` if all were rejected). Approval triggers execution under the inbox item's original `batch_id`, so undo-batch reverts the whole proposal as one unit even when approved in pieces.
