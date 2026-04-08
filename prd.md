# Product Requirements Document — AI Personal Secretary

**Status:** v1 — Final
**Author:** Rareș (with Claude)
**Date:** March 31, 2026
**Scope:** This document covers the v1 (MVP) in full detail. Future versions are outlined in the roadmap (section 11).

---

## 1. Vision

A self-hosted, open-source, model-agnostic AI personal secretary that manages tasks, calendar events, and daily logistics. The user brain-dumps everything into the system — via chat, voice, or quick input — and the AI organizes, reminds, and suggests. The user stays in control: the AI proposes, the user disposes.

The north star is reducing cognitive overhead. Instead of maintaining mental lists and checking multiple apps, the user has one place to dump, review, and act.

---

## 2. Principles

- **Suggest, don't act.** The AI never modifies the user's schedule or task list without explicit approval, unless the user opts into auto-approve mode.
- **Inbox-first.** All input flows through a raw inbox. The AI parses, categorizes, and proposes structured items. The user confirms, edits, or rejects.
- **Model-agnostic.** The backend communicates with any LLM that supports tool calling. The system prompt + tool definitions are the product; the model is swappable.
- **Self-hosted, privacy-first.** User data never leaves infrastructure the user controls. Architecture should make commercial/cloud deployment feasible later without a rewrite.
- **Graceful degradation.** The Telegram bot requires connectivity, but the web UI (when accessed on the same network as the server) works independently of external services. If the LLM provider is unreachable, slash commands and manual CRUD remain fully functional. AI features queue for processing when the provider comes back.

---

## 3. Users

The MVP targets a single user (the deployer). The architecture should make multi-user support a straightforward extension (auth layer, user-scoped data), but it is not an MVP requirement.

Primary persona: a student or knowledge worker juggling multiple organizational contexts (university, extracurriculars, personal life) who is comfortable self-hosting and wants full ownership of their data.

---

## 4. Platform & Architecture

### 4.1 MVP Architecture (Telegram-first)

**Primary interface: Telegram bot.** The user interacts with the secretary through a Telegram bot. This provides chat input, voice note support, push notifications, and inline keyboards (for approve/edit/reject flows) with zero custom UI work. Telegram handles message delivery, notification infrastructure, and cross-platform availability out of the box.

**Secondary interface: Lightweight web UI.** A simple web application for visual operations that a chat interface handles poorly — calendar view, task list browsing, settings management, and manual CRUD forms. This is a read-heavy, form-supplemented dashboard, not a full application. Served directly by the backend.

**Backend:** A containerized API server exposing a REST API consumed by both the Telegram bot handler and the web UI. Clear separation between clients and core logic so future interfaces (native mobile app, other messaging platforms) can be added without touching the backend.

**Database:** An embedded single-file database for the self-hosted MVP. Schema designed so migration to a client-server database for multi-user deployments is straightforward.

**AI layer:** A thin abstraction over LLM APIs. The system defines a system prompt and a set of tool/function definitions. Any model that supports function calling (or can be fine-tuned to) can be plugged in.

**Calendar sync:** Standard calendar protocol (CalDAV) for reading external calendars and writing to the app's dedicated calendar.

**Voice transcription:** Server-side only. Configurable between a local speech-to-text engine (privacy-first) or a cloud transcription API (faster, more accurate).

### 4.2 Future Platform Evolution

See section 11 (Roadmap) for full details. In short: v2 adds a React Native mobile app alongside the Telegram bot, v3 adds knowledge management, and v4 introduces a full web app and commercial deployment.

---

## 5. Core Concepts

### 5.1 Inbox

The central entry point. Everything the user captures — text messages, voice transcriptions, quick-add entries — lands here as raw items. The AI processes inbox items and proposes one or more structured outputs (task, event, note). The user reviews and approves, or the system auto-approves based on user settings.

**Auto-approve mode (disabled by default).** An opt-in toggle, off by default. When enabled, proposed items pass through a deterministic validation layer before being auto-committed: are all required fields present? Is the date parseable? Does the area match a known area? Is the item type unambiguous (clearly a task vs. an event)? If validation passes, the item is committed. If validation fails on any check — including ambiguity about whether something is a task or event — the item goes to the review queue with the standard approve/edit/reject flow. No model self-assessed confidence scores are used; the gate is structural validity, not model certainty.

**Status reports.** After each auto-approved action, the bot sends a programmatic status report summarizing what was changed (e.g., "Created task: Submit ISS project — Due: Friday, April 4 — Area: UBB"). This is enabled by default when auto-approve is on, but can be disabled separately for a fully silent mode.

**Destructive action safeguard.** Destructive actions — deleting a task, deleting an event, cancelling a recurring series — always require manual approval via the inline keyboard, even when auto-approve is on. This is the default behavior and can be reconfigured by the user (at their own risk) to allow auto-approval of destructive actions as well. Three tiers of auto-approve aggressiveness:
- **Standard (default):** Auto-approve creates and non-destructive updates only. Deletes and type-ambiguous items go to review. Status reports on.
- **Aggressive:** Auto-approve everything including deletes. Status reports on.
- **Silent:** Auto-approve everything, status reports off.

### 5.2 Undo

Every write action — whether triggered by the AI, auto-approved, manually approved, or entered via slash commands / web UI — is logged in an action history. The user can undo the last action or the last batch of actions (e.g., if a single brain dump produced three tasks and an event, that entire batch can be undone as one unit).

**In Telegram:** Every status report and confirmation message includes an `[↩ Undo]` inline button. Pressing it reverts the action(s) and confirms the rollback. The undo button remains active for a configurable window (default: 1 hour), after which it expires.

**In the web UI:** A persistent undo bar (similar to Gmail's "message sent — undo") appears after any action, plus a full action history page for reverting older changes.

**Implementation:** Actions are stored as a log of diffs (before/after state). Undo replays the "before" state. This also serves as an audit trail for debugging AI behavior over time.

### 5.3 Tasks

A task represents something the user needs to do.

Fields:
- Title (required)
- Description (optional, markdown)
- Area/context (e.g., "UBB," "ANOSR," "Personal")
- Priority (none, low, medium, high, urgent)
- Due date/time (optional)
- Scheduled date/time (optional — when the user plans to work on it)
- Time estimate (optional)
- Subtasks (ordered checklist)
- Recurrence rule (none, daily, weekly, monthly, custom RRULE)
- Tags (free-form)
- Status (inbox → to-do → in progress → done / cancelled)
- Creation source (chat, voice, quick-add, manual, AI-suggested)

Tasks are displayed in the calendar view on their due/scheduled date and in a dedicated list view with sorting and filtering by area, priority, and status.

### 5.4 Events

Calendar events, pulled from external calendars or created within the app.

The app reads from the user's existing Google Calendar and Apple Calendar (via CalDAV). It does not write to those calendars. Instead, it maintains its own calendar (also exposed via CalDAV) where AI-proposed or manually created events live. This avoids polluting the user's existing calendars while still giving a unified view.

### 5.5 Areas

Top-level organizational contexts. Every task and event can belong to one area. Areas are user-defined (e.g., "University," "ANOSR," "Personal," "Side Projects"). The AI uses areas to generate context-aware briefings ("You have 3 ANOSR deadlines this week but nothing scheduled for your ISS project").

### 5.6 AI Memory & Settings

The AI has access to a user profile/settings file (JSON or YAML) that stores:
- Preferred wake time and wind-down time (for briefing scheduling)
- Notification aggressiveness (minimal / balanced / aggressive)
- Auto-approve toggle and confidence threshold
- Area definitions and their relative priority
- Any persistent context the user wants the AI to know ("I have classes MWF 8–12," "Weekly ANOSR meeting is Thursday 6 PM")

The AI reads this file as part of its system prompt context. The user can edit it directly or through the chat ("remember that my ISS deadline moved to June 5").

---

## 6. Input Methods

### 6.1 Natural Language (Telegram)

The user sends regular Telegram messages — text or voice notes. The bot processes them through the AI layer, which parses intent and proposes actions. Examples:
- "I need to submit the ISS project by Friday."
- "Schedule a meeting with the DPO next Tuesday at 2 PM."
- "What do I have this week?"
- "Move my dentist appointment to Thursday."

Voice notes are transcribed (Whisper or equivalent) and fed into the same AI parsing pipeline as text.

### 6.2 Slash Commands (Telegram)

Direct commands that bypass the LLM entirely. These are instant, free, and work even if the LLM provider is down. They provide a manual, deterministic interface for all core operations.

**Task commands:**
- `/addtask` — Interactive flow: bot asks for title, then optional fields (area, priority, due date, description) step by step via reply prompts or inline keyboards
- `/tasks` — List tasks, with optional filters: `/tasks today`, `/tasks anosr`, `/tasks overdue`
- `/done <task_id or keyword>` — Mark a task complete
- `/edit <task_id>` — Interactive edit flow for an existing task
- `/delete <task_id>` — Delete a task (with confirmation)

**Event commands:**
- `/addevent` — Interactive flow for creating a calendar event
- `/agenda` — Show today's agenda (or `/agenda tomorrow`, `/agenda week`)

**System commands:**
- `/undo` — Undo the last action or last batch of actions
- `/inbox` — Show unprocessed inbox items
- `/briefing` — Trigger a daily briefing on demand
- `/settings` — Link to the web UI settings page or inline settings for key toggles
- `/help` — List all available commands

Slash commands use Telegram's native reply keyboards and inline keyboards for multi-step flows, keeping the interaction fast and chat-native.

### 6.3 Manual Entry (Web UI)

Full CRUD forms for tasks and events in the web dashboard. The user can always bypass both the AI and the Telegram bot to create, edit, or delete items directly. Every entity the AI or the bot can affect is also manually operable through the web UI.

### 6.4 Quick Dump (Telegram)

Any message that isn't a slash command and isn't a reply to an AI question is treated as a brain dump and routed to the inbox. The user can send a stream-of-consciousness message ("ISS project due Friday, also need coffee beans, and remind me to email the DPO") and the AI will parse it into multiple proposed items.

---

## 7. AI Capabilities

### 7.1 Tool Definitions (MVP)

The AI operates through a defined set of tools/functions:

| Tool | Description |
|---|---|
| `create_task` | Create a new task with parsed fields |
| `update_task` | Modify an existing task |
| `complete_task` | Mark a task as done |
| `delete_task` | Remove a task |
| `list_tasks` | Query tasks with filters (area, priority, date range, status) |
| `create_event` | Create a calendar event on the app's calendar |
| `update_event` | Modify an existing event |
| `delete_event` | Remove an event |
| `list_events` | Query events across all calendars for a date range |
| `get_briefing` | Generate a daily or weekly summary |
| `read_settings` | Access user preferences and persistent memory |
| `update_memory` | Store a new persistent fact in the user profile |

Each tool has a simple, well-defined schema. The total set is small enough that even 7B-parameter models with function calling can handle it reliably.

### 7.2 Briefings

**Daily briefing:** Generated at the user's configured wake time (or on demand). Contains: today's events, overdue tasks, tasks due today, top 3 suggested tasks to work on (based on priority, deadline proximity, and time estimates), and a plain-language summary.

**Weekly review:** Generated on a configurable day (default: Sunday evening). Contains: tasks completed this week, tasks that slipped, upcoming deadlines next week, areas with no scheduled activity (to surface neglected responsibilities), and a suggested plan for the week ahead.

Briefings are delivered as Telegram messages. The user receives a push notification from Telegram itself — no custom push infrastructure (FCM/APNs) needed.

### 7.3 Proactive Notifications

Configurable by aggressiveness level:

- **Minimal:** Only deadline reminders (configurable lead time: 1 hour, 1 day, etc.).
- **Balanced:** Deadline reminders + daily briefing + conflict alerts ("You have two things at 3 PM Tuesday").
- **Aggressive:** All of the above + idle nudges ("You've had 2 free hours — want to tackle the ISS report?") + context switches ("Your ANOSR meeting starts in 15 min, here's what you have pending for it").

### 7.4 Suggest Mode

The default operating mode. When the AI processes inbox items or wants to propose a schedule change, it sends a Telegram message with an inline keyboard:

```
📋 Suggestion: Create task
  Title: Submit ISS project
  Due: Friday, April 4
  Area: UBB
  Priority: High

  [✅ Approve]  [✏️ Edit]  [❌ Reject]
```

Pressing "Approve" commits the item immediately. "Edit" starts an interactive flow where the bot asks which fields to change. "Reject" discards the proposal and logs it.

In auto-approve mode, items are committed directly and the bot sends a confirmation message instead of a suggestion card. Items below the confidence threshold still show the interactive suggestion.

---

## 8. Calendar Integration

**Read:** The app connects to Google Calendar and Apple Calendar via CalDAV/Google Calendar API and pulls events into a unified calendar view. Sync is periodic (configurable interval, default 15 minutes) and on-demand (pull-to-refresh).

**Write:** The app creates a dedicated calendar (e.g., "Secretary") on the user's Google/Apple account via CalDAV. AI-created and manually-created events within the app are written to this calendar only. This keeps the user's original calendars clean and makes the app's contributions easy to identify or remove.

**Unified view:** The app's calendar view overlays all synced calendars plus the app's own calendar plus tasks (on their due/scheduled dates), giving a single view of the user's full schedule.

---

## 9. Data Model (Simplified)

```
User
├── Settings (JSON blob: wake_time, notification_level, auto_approve, areas[], memory[])
├── InboxItem[]
│   ├── id, raw_text, source (chat|voice|quick_add), created_at
│   ├── status (pending|processed|rejected)
│   └── proposed_actions[] → Task | Event
├── Task[]
│   ├── id, title, description, area, priority, status
│   ├── due_at, scheduled_at, time_estimate_minutes
│   ├── recurrence_rule, tags[], subtasks[]
│   └── created_at, updated_at, source
├── Event[]
│   ├── id, title, description, area
│   ├── start_at, end_at, location, is_all_day
│   ├── calendar_source (google|apple|internal)
│   └── created_at, updated_at
└── ChatMessage[]
    ├── id, role (user|assistant), content
    ├── tool_calls[], tool_results[]
    └── created_at
```

---

## 10. Non-Functional Requirements

- **Latency:** AI responses should feel conversational. Target < 3s for simple tool calls, < 8s for briefing generation. Slash commands should respond within 500ms (no LLM round-trip). Web UI page loads should be under 1s.
- **Storage:** All data stored locally in SQLite. Sync to server is optional and additive. No external dependencies for core functionality beyond the LLM API.
- **Security:** API keys for LLM providers and calendar accounts stored in encrypted local config. No telemetry, no analytics, no data exfiltration. HTTPS for all sync traffic.
- **Extensibility:** Plugin-friendly architecture for future integrations (email, Obsidian vault, shared drives, university APIs). New tools can be added to the AI's tool set without modifying the core.

---

## 11. Roadmap

### v1 — MVP (this document)

The self-hosted Telegram-first personal secretary. Everything described in sections 1–10 of this document.

Core deliverables:
- Telegram bot as primary interface (text, voice notes, slash commands, inline keyboards)
- Lightweight web UI for calendar view, task list, settings, and manual CRUD
- Inbox-first capture with AI parsing and suggest mode
- Slash commands for direct task/event CRUD bypassing the LLM
- Auto-approve mode (disabled by default) with structural validation and destructive action safeguards
- Undo for last action or last batch, with action history log
- Full task CRUD with areas, priorities, subtasks, recurrence, time estimates
- Calendar sync (read from Google/Apple, write to dedicated CalDAV calendar)
- Unified calendar + task view (web UI)
- Daily and weekly AI briefings (delivered via Telegram)
- Configurable notification aggressiveness (minimal/balanced/aggressive)
- Voice note transcription (server-side Whisper or cloud API)
- User settings and AI memory file
- Self-hosted Docker deployment
- Model-agnostic LLM layer

### v2 — Native App & Integrations

Expand from a Telegram bot + web dashboard to a standalone mobile experience, and add integrations that go beyond calendar.

Planned features:
- React Native mobile app with native chat UI, replacing Telegram as the primary interface for users who prefer it (Telegram bot remains as an alternative)
- Home screen widget for quick capture (text field that dumps to inbox)
- Offline-first local storage with background sync to server
- Email inbox integration (read-only parsing of emails into tasks/events)
- Multi-user auth (allow multiple users on a single deployment)
- Kanban board view for tasks
- WhatsApp / Discord bot support as alternative messaging interfaces
- Fine-tuned small model optimized for the app's specific tool set

### v3 — Second Brain & Knowledge Management

Turn the secretary into a full personal knowledge system.

Planned features:
- Obsidian-compatible knowledge vault (store notes, meeting takeaways, learning in structured markdown; sync to an Obsidian vault or access through the app)
- Shared calendars and collaborative task management (for teams, student orgs)
- Google Drive integration (reference shared docs, attach files to tasks)
- University schedule API integration (auto-import class timetables)

### v4 — Commercial & Scale

Prepare for multi-tenant deployment and public availability.

Planned features:
- Commercial cloud deployment (managed hosting option)
- End-to-end encryption / zero-knowledge architecture
- Full web app with feature parity to native mobile app
- Plugin/extension marketplace for community-built integrations
- Onboarding flow and documentation for non-technical users

---

## 12. Resolved Decisions

1. **Voice transcription:** Server-side only. The backend handles all transcription of Telegram voice notes (.ogg). Two options configurable in settings: local Whisper (privacy-first, slower) or cloud transcription API (faster, more accurate). No on-device processing.
2. **Auto-approve confidence scoring:** Hybrid/structural validation (see section 5.1). A deterministic validation layer checks field completeness, date parseability, area matching, and type ambiguity. No model self-assessed confidence scores. Auto-approve is disabled by default.
3. **Calendar write-back:** The app writes only to its own isolated calendar, exposed via CalDAV so the user can subscribe to it from Google Calendar, Apple Calendar, or any other client. No write access to the user's existing calendars.
4. **Telegram bot polling vs. webhooks:** Support both. Polling as the default for ease of self-hosting (no public URL required). Webhooks as an option for users with a reverse proxy / public-facing server.
5. **Web UI auth:** Token-based authentication. Additionally, a documented deployment option for Tailscale-only access (network-level restriction, no auth needed on the app layer).

---

## 13. Open Questions

1. **Project name:** TBD.

---
---

# Appendix A — Technical Specification

This appendix details the implementation-level technology choices for v1. Each choice includes alternatives considered and trade-offs. It is separate from the product requirements above and can be revised independently as technical constraints evolve.

---

## A.1 Backend Language & Framework

### Language: Python 3.12+

**Chosen over:** Go, TypeScript/Node.js, Rust

| | Pros | Cons |
|---|---|---|
| **Python** | Rareș's primary language — fastest path to a working product. Richest ecosystem for AI/ML libraries (LiteLLM, Whisper, etc.). Every dependency in this spec has a mature Python library. Async support is good enough via asyncio. | Slower runtime than Go/Rust. GIL limits true parallelism (mitigated by async I/O for this use case). Type safety is opt-in, not enforced. |
| **Go** | Excellent concurrency model, compiles to a single binary (trivial deployment), fast runtime. Strong for API servers. | Weaker AI/ML ecosystem — LiteLLM, faster-whisper, and most LLM tooling is Python-first. Would require writing custom abstractions or calling Python services. Rareș has limited Go experience. |
| **TypeScript/Node.js** | Would share a language with a future React Native frontend. Good async model. | AI/ML ecosystem is weaker than Python. Would need Node.js in the stack regardless of web UI choice. Rareș is less comfortable with it than Python. |
| **Rust** | Maximum performance, memory safety. | Overkill for this workload. Extremely slow development velocity for a solo project. Almost no AI/ML library ecosystem. |

**Verdict:** Python is the clear choice. The AI/ML ecosystem alignment alone makes it the only practical option for a solo developer building an LLM-powered app.

### Framework: FastAPI

**Chosen over:** Flask, Django, Litestar

| | Pros | Cons |
|---|---|---|
| **FastAPI** | Async-native (critical for concurrent bot + web + AI calls). Auto-generated OpenAPI docs. Built-in Pydantic validation. Lightweight — no opinions about project structure. Excellent performance for Python (Uvicorn/ASGI). | Smaller ecosystem than Django (no built-in admin, auth, ORM). Requires manual setup for things Django gives you for free. Less opinionated — more decisions to make. |
| **Flask** | Simpler mental model, massive ecosystem of extensions. Most tutorials/examples use Flask. | Synchronous by default. Async support exists but is bolted on, not native. Would need Celery or similar for background tasks that FastAPI handles natively. |
| **Django** | Batteries-included: ORM, admin panel, auth, forms. The admin panel alone could replace part of the web UI. | Heavyweight for a single-user self-hosted app. Async support is improving but still second-class. Opinionated ORM (Django ORM) makes a future PostgreSQL migration path different from SQLAlchemy's. |
| **Litestar** | Modern, async-native, similar to FastAPI but with more built-in features (dependency injection, guards). | Much smaller community and ecosystem. Fewer tutorials, Stack Overflow answers, and third-party integrations. Riskier bet for long-term maintenance. |

**Verdict:** FastAPI. Async is non-negotiable (the app runs a bot, a web server, AI calls, and scheduled jobs concurrently), and FastAPI has the best balance of performance, simplicity, and ecosystem for this.

### Project structure

```
secretary/
├── bot/              # Telegram bot handlers, slash commands, inline keyboards
├── web/              # Web UI routes, templates, static assets
├── core/             # Business logic (task CRUD, event CRUD, inbox processing)
├── ai/               # LLM abstraction, system prompt, tool definitions
├── calendar_sync/    # CalDAV read/write, Google Calendar API
├── transcription/    # Voice note processing (Whisper / cloud API)
├── db/               # Models, migrations, database access
├── scheduler/        # Briefing scheduling, notification triggers
├── config/           # Settings, user memory file, environment config
└── main.py           # App entrypoint
```

### Containerization: Docker + docker-compose

**Chosen over:** bare metal, Podman, Nix flake

| | Pros | Cons |
|---|---|---|
| **Docker + compose** | Industry standard for self-hosted apps. Single `docker-compose up` to run everything. Easy to document, easy to reproduce. Works on Linux, macOS, Windows. | Adds a layer of abstraction. Slightly more complex debugging (logs, exec into container). Requires Docker installed on the host. |
| **Bare metal** | No containerization overhead. Simplest possible deployment on a single machine. | "Works on my machine" problems. Dependency conflicts with host system. Hard to document reproducibly. |
| **Podman** | Rootless by default, Docker-compatible. Better security posture. | Smaller user base, fewer tutorials. docker-compose compatibility exists but is less battle-tested. |
| **Nix flake** | Perfectly reproducible builds. Rareș uses NixOS. | Very steep learning curve for contributors. Niche — most potential users of an open-source project won't know Nix. Can offer as an alternative deployment option alongside Docker. |

**Verdict:** Docker + compose as the primary deployment. A Nix flake can be added later as a community contribution given Rareș's NixOS background.

---

## A.2 Database

### Engine: SQLite via aiosqlite

**Chosen over:** PostgreSQL, DuckDB, plain JSON files

| | Pros | Cons |
|---|---|---|
| **SQLite** | Zero-config, single-file database. Backup is a file copy. Perfect for single-user self-hosted. Surprisingly performant — handles millions of rows. No external service to run. aiosqlite provides async access. | No concurrent write access from multiple processes (fine for single-user, problematic for multi-user). Limited full-text search compared to PostgreSQL. No built-in JSON querying (though extensions exist). |
| **PostgreSQL** | Full-featured relational database. Excellent JSON support, full-text search, concurrent access. The right choice for multi-user. | Requires running a separate service (another Docker container). Overkill for single-user MVP. More complex backup/restore. Configuration overhead. |
| **DuckDB** | Excellent for analytical queries. Embedded like SQLite. | Designed for OLAP, not OLTP. Poor fit for a transactional app with many small writes (task creation, status updates). |
| **Plain JSON files** | Simplest possible implementation. No ORM, no migrations, just read/write files. | No querying beyond loading everything into memory. No transactions, no concurrent access safety. Breaks down immediately at any meaningful data volume. Not a serious option. |

**Verdict:** SQLite for v1. Design the schema and ORM layer so that switching to PostgreSQL in v2 (for multi-user) requires changing one connection string.

### ORM: SQLAlchemy 2.0 (async mode)

**Chosen over:** Tortoise ORM, SQLModel, raw SQL

| | Pros | Cons |
|---|---|---|
| **SQLAlchemy 2.0** | Industry standard Python ORM. Supports both SQLite and PostgreSQL with the same models. Async mode via asyncio. Extremely mature — every edge case is documented. Alembic (migration tool) is built for it. | Verbose model definitions. Steep learning curve for advanced features. The 2.0 API is newer and has fewer tutorials than 1.x. |
| **SQLModel** | Built by the FastAPI creator (tiangolo). Combines SQLAlchemy + Pydantic in one model definition — less boilerplate. | Thin wrapper around SQLAlchemy — when you hit edge cases, you're debugging SQLAlchemy anyway. Less mature, smaller community. Async support is inherited from SQLAlchemy but less documented in SQLModel-specific contexts. |
| **Tortoise ORM** | Async-first design (unlike SQLAlchemy which added async later). Django-like syntax. | Smaller community. Fewer supported databases. Migration tooling (Aerich) is less mature than Alembic. Riskier long-term bet. |
| **Raw SQL** | Maximum control, no abstraction overhead. Easy to debug — what you write is what runs. | No migration tooling. Manual mapping between query results and Python objects. Painful to switch databases (SQL dialect differences). Doesn't scale with codebase complexity. |

**Verdict:** SQLAlchemy 2.0. The migration path to PostgreSQL and Alembic integration are decisive. SQLModel is a reasonable alternative if boilerplate becomes painful — it's a compatible layer, not a competing one, so switching later is cheap.

### Migrations: Alembic

**Chosen over:** manual schema management, Aerich

| | Pros | Cons |
|---|---|---|
| **Alembic** | The standard migration tool for SQLAlchemy. Version-controlled schema changes. Auto-generates migrations from model diffs. Works with SQLite and PostgreSQL. | Another dependency. Requires discipline to generate and review migrations. Auto-generated migrations sometimes need manual editing. |
| **Manual SQL** | No dependencies. Full control. | No version history. Impossible to track what schema version a given database is at. Collaborators can't sync schema changes. Recipe for data loss. |
| **Aerich** | Designed for Tortoise ORM. | Only works with Tortoise, not SQLAlchemy. Not applicable here. |

**Verdict:** Alembic. Non-negotiable if using SQLAlchemy — the cost of not having migrations is paid in data loss and debugging time.

---

## A.3 Telegram Bot

### Library: aiogram 3.x

**Chosen over:** python-telegram-bot, Telethon, raw HTTP

| | Pros | Cons |
|---|---|---|
| **aiogram 3.x** | Async-native (matches FastAPI's event loop). Modern API design with routers, middleware, and filters. First-class inline keyboard and callback query support. Active development. | Smaller community than python-telegram-bot. Fewer Stack Overflow answers. Documentation is good but less extensive. Breaking changes between 2.x and 3.x mean some tutorials are outdated. |
| **python-telegram-bot** | Largest community, most tutorials, most Stack Overflow answers. Very well documented. | Historically synchronous. v20+ added async support, but it's a retrofit — the library wasn't designed async-first. Integrating with FastAPI's async loop requires more glue code. |
| **Telethon** | Full Telegram client API (not just bot API). Can do things bots can't. | Overkill — uses MTProto (Telegram's internal protocol) instead of the simpler Bot API. More complex setup. Intended for user accounts, not bots. |
| **Raw HTTP** | No dependency. Full control over Telegram Bot API calls. | Reinventing the wheel. No built-in conversation state, middleware, or keyboard builders. Significant development time for features that libraries provide for free. |

**Verdict:** aiogram 3.x. The async-native design is the deciding factor — it shares an event loop with FastAPI naturally, avoiding the concurrency headaches of mixing sync and async code.

---

## A.4 Web UI

### Approach: Server-rendered (Jinja2 + HTMX + Alpine.js)

**Chosen over:** SvelteKit, React (SPA), Next.js, plain HTML

| | Pros | Cons |
|---|---|---|
| **Jinja2 + HTMX + Alpine.js** | No JavaScript build step. No Node.js dependency. The entire stack is Python. HTMX handles dynamic updates (search, inline editing, approve/reject) with HTML responses from the server. Alpine.js covers client-side state (dropdowns, modals). Fast to develop for a read-heavy dashboard. | Limited for highly interactive UIs — drag-and-drop, complex calendar interactions, and real-time updates are harder than with a JS framework. Calendar week view specifically may push HTMX's limits. Smaller community for HTMX + Alpine.js patterns. |
| **SvelteKit** | Excellent developer experience. Reactive by default. Good for interactive UIs (calendar, drag-and-drop). Compiles to small bundles. | Adds Node.js to the stack. Separate build step. Two languages (Python + JS/TS) to maintain. More infrastructure for what's supposed to be a lightweight dashboard. |
| **React (Vite SPA)** | Largest ecosystem, most UI component libraries (calendar widgets, etc.). Rareș will need React knowledge for React Native in v2 anyway. | Heaviest option. Full SPA with client-side routing. Requires a separate dev server. Overkill for a read-heavy dashboard. Slow initial load. |
| **Next.js** | React-based with server-side rendering. Good developer experience. | Even heavier than plain React. Requires Node.js runtime in production. Two backend services to run (FastAPI + Next.js). Absurdly overengineered for this use case. |
| **Plain HTML + CSS** | Simplest possible option. No dependencies. | No interactivity without JavaScript. Every action requires a full page reload. Poor UX for task editing, inbox review, and calendar navigation. |

**Verdict:** Jinja2 + HTMX + Alpine.js for v1. This is the highest-leverage choice for a solo developer who wants a functional dashboard without maintaining a JS build pipeline. If the calendar view specifically proves too limited, that single view can be replaced with a standalone Svelte or React component embedded in the page without rewriting the rest.

### CSS: Tailwind CSS (CDN)

**Chosen over:** Bootstrap, custom CSS, Pico CSS

| | Pros | Cons |
|---|---|---|
| **Tailwind (CDN)** | Utility-first — no naming conventions to invent. Looks clean out of the box. CDN means no build step. Extensive documentation. | CDN version includes the full stylesheet (~300KB). Utility classes make HTML verbose. Harder to maintain consistent design without a component library. |
| **Bootstrap** | Familiar, lots of pre-built components. Good for dashboards. | Looks generic ("Bootstrap-y"). Heavier CSS. Harder to customize deeply. |
| **Custom CSS** | Full control, smallest file size. | Slow to develop. Requires design skills. Inconsistent without discipline. |
| **Pico CSS** | Minimal, classless — just write semantic HTML and it looks decent. | Very limited customization. No utility classes. Falls apart for anything beyond basic content pages. |

**Verdict:** Tailwind via CDN. The CDN size penalty is acceptable for MVP; a build step can be added later to purge unused classes if needed.

---

## A.5 AI / LLM Layer

### Abstraction: LiteLLM

**Chosen over:** custom adapter per provider, Langchain, Instructor, raw HTTP

| | Pros | Cons |
|---|---|---|
| **LiteLLM** | Unified `completion()` call across 100+ providers. Swap models by changing a string. Normalizes function/tool calling across OpenAI, Anthropic, Ollama, Mistral, etc. Lightweight — it's a translation layer, not a framework. Actively maintained. | Another dependency. Adds a layer of abstraction over provider SDKs — when something breaks, debugging goes through LiteLLM's translation logic. Occasionally lags behind new provider features. Tool calling normalization isn't perfect across all providers. |
| **Custom adapters** | Full control. No third-party abstraction. Can optimize for each provider's quirks. | Significant development and maintenance time. Every new provider means writing a new adapter. Tool calling format differences between OpenAI, Anthropic, and Ollama are non-trivial to handle. |
| **LangChain** | Large ecosystem, lots of pre-built chains and agents. Good for complex multi-step AI workflows. | Extremely heavyweight for this use case. Over-abstracted — adds layers of complexity for what is essentially "send a prompt, get a tool call back." Notoriously hard to debug. Dependency bloat. |
| **Instructor** | Excellent for structured output extraction (Pydantic models from LLM responses). Clean API. | Focused specifically on structured extraction, not general tool calling. Would still need a separate layer for the conversational chat interface. Could complement LiteLLM but doesn't replace it. |
| **Raw HTTP** | No dependencies. Full control over request/response format. | Must handle auth, retries, streaming, error codes, and tool calling format differences per provider manually. Massive time sink for no real benefit. |

**Verdict:** LiteLLM. The model-agnostic requirement makes this the obvious choice — it solves the hardest part (normalizing tool calling across providers) with minimal code. Instructor can be layered on top later if structured extraction needs become more complex.

### System prompt: Jinja2 template

**Chosen over:** hardcoded string, separate prompt files, prompt management tools

| | Pros | Cons |
|---|---|---|
| **Jinja2 template** | Dynamic — user settings, memory, and area definitions are injected at render time. Same templating engine already used for the web UI. Supports conditionals and loops (e.g., only include areas that exist). | Mixing prompt engineering with template syntax can get messy. No built-in versioning or A/B testing of prompts. |
| **Hardcoded string** | Simplest. Easy to read. | Can't inject user-specific data without string concatenation, which gets ugly fast. |
| **Prompt management tool (e.g., PromptLayer)** | Version control, A/B testing, analytics. | External dependency for a self-hosted app. Overkill for single-user MVP. |

**Verdict:** Jinja2 template. Practical, lightweight, and already in the stack.

---

## A.6 Calendar Sync

### Google Calendar: google-api-python-client

**Chosen over:** CalDAV for Google, gcsa

| | Pros | Cons |
|---|---|---|
| **google-api-python-client** | Official Google library. Full access to Google Calendar API features (color, reminders, conferencing). Well documented. | OAuth 2.0 setup is tedious (Google Cloud Console, consent screen, credentials). Heavyweight library (pulls in many Google dependencies). Google-specific — doesn't help with Apple Calendar. |
| **CalDAV for Google** | Google Calendar supports CalDAV. Would mean one protocol for all calendar providers. | Google's CalDAV support is limited and poorly documented. Some features (reminders, colors) aren't exposed via CalDAV. Google may deprecate CalDAV access further. |
| **gcsa (Google Calendar Simple API)** | Simpler wrapper around the official library. Less boilerplate. | Small project, single maintainer. Risk of abandonment. Still requires the same OAuth setup underneath. |

**Verdict:** google-api-python-client for Google Calendar specifically. CalDAV (via the caldav library) for everything else — Apple Calendar, Fastmail, Nextcloud, etc.

### CalDAV: caldav Python library

This is effectively the only mature Python CalDAV library. No meaningful alternatives exist. It works with iCloud, Fastmail, Nextcloud, and any standard CalDAV server.

---

## A.7 Voice Transcription

### Local: faster-whisper

**Chosen over:** vanilla OpenAI Whisper, Vosk, DeepSpeech

| | Pros | Cons |
|---|---|---|
| **faster-whisper** | 4–8x faster than vanilla Whisper via CTranslate2 optimization. Runs on CPU (GPU optional). Same model quality as Whisper. Configurable model sizes (tiny/small/medium/large). | Still requires significant CPU for larger models. Transcription of a 30-second voice note takes 2–5 seconds on CPU with the small model. Adds ~500MB to the Docker image (for the model). |
| **Vanilla Whisper** | Reference implementation. Simplest to set up. | Significantly slower than faster-whisper. Higher memory usage. No reason to use this when faster-whisper exists. |
| **Vosk** | Very lightweight, fast on CPU. Good for real-time streaming. | Lower accuracy than Whisper, especially for non-English audio. Smaller model selection. Less active development. |
| **DeepSpeech** | Mozilla project, fully open source. | Effectively abandoned (last release 2021). Accuracy is behind Whisper. |

**Verdict:** faster-whisper for local transcription. The speed improvement over vanilla Whisper is substantial and matters for the UX — voice notes should feel like they're processed in near real-time.

### Cloud: OpenAI Whisper API

**Chosen over:** Google Cloud Speech-to-Text, AWS Transcribe, Deepgram

| | Pros | Cons |
|---|---|---|
| **OpenAI Whisper API** | Same Whisper model but run on OpenAI's infrastructure. Very cheap (~$0.006/min). Simple API. High accuracy. | Sends audio to OpenAI's servers (privacy consideration). Requires an OpenAI API key. |
| **Google Cloud STT** | Good accuracy, especially for long audio. Supports many languages. | More complex API. Requires Google Cloud setup (separate from Calendar OAuth). More expensive for short audio clips. |
| **Deepgram** | Fast, accurate, good for real-time. | More expensive. Smaller company — longevity risk. |

**Verdict:** OpenAI Whisper API as the cloud option. Cheapest, simplest, and most accurate for short voice notes (which is the primary use case — messages are typically 5–30 seconds).

### Pipeline

.ogg (from Telegram) → ffmpeg conversion to 16kHz WAV → transcription (local or cloud) → text fed into the AI parsing pipeline as a regular message.

---

## A.8 Scheduling & Background Jobs

### Library: APScheduler (AsyncIOScheduler)

**Chosen over:** Celery + Redis, arq, simple cron, asyncio.create_task with sleep

| | Pros | Cons |
|---|---|---|
| **APScheduler** | Runs in-process with FastAPI (shares the async event loop). No external services needed. Supports cron-like schedules, interval jobs, and one-off jobs. Lightweight. Job persistence via SQLAlchemy (can store jobs in the same SQLite database). | Single-process only — if the app restarts, in-memory jobs are lost (mitigated by job persistence to DB). Not designed for distributed workloads. Can't scale horizontally for multi-user. |
| **Celery + Redis** | Industry standard for distributed task queues. Scales horizontally. Retry logic, task chaining, monitoring (Flower). | Requires Redis (another service in docker-compose). Heavyweight for single-user MVP. Complex configuration. Overkill. |
| **arq** | Async-native job queue (Redis-backed). Lighter than Celery. | Still requires Redis. Less mature than Celery. Smaller community. |
| **asyncio.create_task + sleep** | Zero dependencies. Just schedule coroutines in the event loop. | No persistence — all scheduled jobs lost on restart. No cron-like scheduling syntax. Manual reimplementation of everything APScheduler gives you. Fragile. |

**Verdict:** APScheduler. Right-sized for single-user MVP. When v2 needs multi-user, migrate to Celery + Redis — the job definitions (sync calendar, send briefing, trigger reminder) stay the same, only the executor changes.

---

## A.9 Auth & Security

### Web UI: Token-based auth

**Chosen over:** username/password, OAuth, session-based

| | Pros | Cons |
|---|---|---|
| **Token-based** | Simple. No user database. Server generates a random token on first run, user adds it as a cookie or header. One line of middleware to validate. | Single token — no granular permissions, no multi-user. Token management is manual (copy from console/config file). |
| **Username/password** | Familiar UX. | Requires a user database, password hashing, session management. Overkill for single-user. |
| **OAuth (e.g., "Sign in with Google")** | No password to manage. Familiar UX. | Requires external OAuth provider setup. Adds complexity. Ironic for a privacy-first self-hosted app. |

**Verdict:** Token-based for v1. The Tailscale deployment option makes even this optional — if the server is only accessible on a Tailscale network, no auth is needed at the app layer.

### Telegram auth

The bot only responds to a configured Telegram user ID (set in `.env` during setup). Messages from other users are silently ignored. This is the simplest possible auth and is standard practice for personal Telegram bots.

### Secrets management

LLM API keys, Google OAuth credentials, and the web UI token are stored in a `.env` file mounted into the Docker container. Never committed to version control. For production hardening, Docker secrets or a tool like SOPS can be layered on top.

---

## A.10 Dependencies Summary

| Component | Library / Tool | Purpose |
|---|---|---|
| Backend framework | FastAPI + Uvicorn | API server, web UI serving |
| Telegram bot | aiogram 3.x | Bot handlers, inline keyboards |
| Database | SQLite + aiosqlite | Data storage |
| ORM | SQLAlchemy 2.0 (async) | Data models, query building |
| Migrations | Alembic | Schema versioning |
| LLM abstraction | LiteLLM | Model-agnostic AI calls |
| Web templating | Jinja2 | Server-rendered HTML |
| Web interactivity | HTMX + Alpine.js | Dynamic UI without JS build step |
| CSS | Tailwind CSS (CDN) | Styling |
| Calendar (Google) | google-api-python-client | Google Calendar API |
| Calendar (CalDAV) | caldav | Apple Calendar, generic CalDAV |
| Transcription (local) | faster-whisper | On-server speech-to-text |
| Transcription (cloud) | OpenAI Whisper API | Cloud speech-to-text |
| Audio conversion | ffmpeg | .ogg to .wav for transcription |
| Scheduling | APScheduler | Periodic jobs, briefings, reminders |
| Containerization | Docker + docker-compose | Deployment |
