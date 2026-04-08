"""OpenAI function-calling tool definitions for the secretary AI."""

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new task for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title of the task.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description or notes.",
                    },
                    "area": {
                        "type": "string",
                        "description": "Life area this task belongs to (e.g. work, personal, health).",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["none", "low", "medium", "high", "urgent"],
                        "description": "Priority level. Defaults to 'none'.",
                    },
                    "due_at": {
                        "type": "string",
                        "description": "Due date/time in ISO 8601 format.",
                    },
                    "scheduled_at": {
                        "type": "string",
                        "description": "Scheduled date/time in ISO 8601 format.",
                    },
                    "time_estimate_minutes": {
                        "type": "integer",
                        "description": "Estimated time to complete in minutes.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags/labels for the task.",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update an existing task's fields.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID of the task to update.",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title.",
                    },
                    "description": {
                        "type": "string",
                        "description": "New description.",
                    },
                    "area": {
                        "type": "string",
                        "description": "New area.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["none", "low", "medium", "high", "urgent"],
                        "description": "New priority level.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["inbox", "to_do", "in_progress", "done", "cancelled"],
                        "description": "New status.",
                    },
                    "due_at": {
                        "type": "string",
                        "description": "New due date/time in ISO 8601 format.",
                    },
                    "scheduled_at": {
                        "type": "string",
                        "description": "New scheduled date/time in ISO 8601 format.",
                    },
                    "time_estimate_minutes": {
                        "type": "integer",
                        "description": "New time estimate in minutes.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New set of tags (replaces existing).",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID of the task to complete.",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Permanently delete a task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID of the task to delete.",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List tasks with optional filters. Returns active tasks by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "Filter by life area.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["none", "low", "medium", "high", "urgent"],
                        "description": "Filter by priority.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["inbox", "to_do", "in_progress", "done", "cancelled"],
                        "description": "Filter by status.",
                    },
                    "due_before": {
                        "type": "string",
                        "description": "Show tasks due before this ISO 8601 date/time.",
                    },
                    "due_after": {
                        "type": "string",
                        "description": "Show tasks due after this ISO 8601 date/time.",
                    },
                    "overdue": {
                        "type": "boolean",
                        "description": "If true, show only overdue tasks.",
                    },
                    "search": {
                        "type": "string",
                        "description": "Search term to match in task titles.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a new calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the event.",
                    },
                    "start_at": {
                        "type": "string",
                        "description": "Start date/time in ISO 8601 format.",
                    },
                    "end_at": {
                        "type": "string",
                        "description": "End date/time in ISO 8601 format.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description or notes.",
                    },
                    "area": {
                        "type": "string",
                        "description": "Life area this event belongs to.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location.",
                    },
                    "is_all_day": {
                        "type": "boolean",
                        "description": "Whether this is an all-day event.",
                    },
                },
                "required": ["title", "start_at", "end_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Update an existing calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "integer",
                        "description": "ID of the event to update.",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title.",
                    },
                    "start_at": {
                        "type": "string",
                        "description": "New start date/time in ISO 8601 format.",
                    },
                    "end_at": {
                        "type": "string",
                        "description": "New end date/time in ISO 8601 format.",
                    },
                    "description": {
                        "type": "string",
                        "description": "New description.",
                    },
                    "area": {
                        "type": "string",
                        "description": "New area.",
                    },
                    "location": {
                        "type": "string",
                        "description": "New location.",
                    },
                    "is_all_day": {
                        "type": "boolean",
                        "description": "Whether this is an all-day event.",
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Permanently delete a calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "integer",
                        "description": "ID of the event to delete.",
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List calendar events with optional filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_after": {
                        "type": "string",
                        "description": "Show events starting after this ISO 8601 date/time.",
                    },
                    "start_before": {
                        "type": "string",
                        "description": "Show events starting before this ISO 8601 date/time.",
                    },
                    "area": {
                        "type": "string",
                        "description": "Filter by area.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_briefing",
            "description": "Generate a daily or weekly briefing summarizing upcoming tasks and events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["daily", "weekly"],
                        "description": "Type of briefing to generate.",
                    },
                },
                "required": ["type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_settings",
            "description": "Read the current user settings (areas, memory, notification preferences, etc.).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory",
            "description": "Store a fact or preference about the user for future reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The fact or preference to remember.",
                    },
                },
                "required": ["fact"],
            },
        },
    },
]

TOOL_NAMES: set[str] = {tool["function"]["name"] for tool in TOOLS}
