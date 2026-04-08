from datetime import datetime, timedelta

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from secretary.db.base import Base, UTCDateTime, utcnow

# --- Association table ---

task_tags = Table(
    "task_tags",
    Base.metadata,
    Column("task_id", Integer, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


# --- Models ---


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    wake_time: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    wind_down_time: Mapped[str] = mapped_column(String(5), nullable=False, default="22:00")
    notification_level: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("notification_level IN ('minimal', 'balanced', 'aggressive')"),
        nullable=False,
        default="balanced",
    )
    auto_approve_mode: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("auto_approve_mode IN ('off', 'standard', 'aggressive', 'silent')"),
        nullable=False,
        default="off",
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    areas: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    memory: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    undo_expiry_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    ai_context_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


class InboxItem(Base):
    __tablename__ = "inbox_items"
    __table_args__ = (
        Index("ix_inbox_items_status", "status"),
        Index("ix_inbox_items_batch_id", "batch_id"),
        Index("ix_inbox_items_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("source IN ('chat', 'voice', 'quick_add')"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("status IN ('pending', 'proposed', 'processed', 'rejected')"),
        nullable=False,
        default="pending",
    )
    proposed_actions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(back_populates="inbox_item")
    events: Mapped[list["Event"]] = relationship(back_populates="inbox_item")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_due_at", "status", "due_at"),
        Index("ix_tasks_status_area", "status", "area"),
        Index("ix_tasks_due_at", "due_at"),
        Index("ix_tasks_scheduled_at", "scheduled_at"),
        Index("ix_tasks_inbox_item_id", "inbox_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint("priority IN ('none', 'low', 'medium', 'high', 'urgent')"),
        nullable=False,
        default="none",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("status IN ('inbox', 'to_do', 'in_progress', 'done', 'cancelled')"),
        nullable=False,
        default="to_do",
    )
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    time_estimate_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("source IN ('chat', 'voice', 'quick_add', 'manual', 'ai_suggested')"),
        nullable=False,
        default="manual",
    )
    inbox_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("inbox_items.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # Relationships
    inbox_item: Mapped["InboxItem | None"] = relationship(back_populates="tasks")
    subtasks: Mapped[list["Subtask"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="Subtask.position"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=task_tags, back_populates="tasks")


class Subtask(Base):
    __tablename__ = "subtasks"
    __table_args__ = (Index("ix_subtasks_task_id", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    task: Mapped["Task"] = relationship(back_populates="subtasks")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_start_end", "start_at", "end_at"),
        Index("ix_events_area", "area"),
        Index("ix_events_inbox_item_id", "inbox_item_id"),
        UniqueConstraint("calendar_source", "external_id", name="uq_events_source_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calendar_source: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("calendar_source IN ('google', 'apple', 'caldav', 'internal')"),
        nullable=False,
        default="internal",
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    inbox_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("inbox_items.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # Relationships
    inbox_item: Mapped["InboxItem | None"] = relationship(back_populates="events")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(secondary=task_tags, back_populates="tags")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')"),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ActionLog(Base):
    __tablename__ = "action_log"
    __table_args__ = (
        Index("ix_action_log_batch_id", "batch_id"),
        Index("ix_action_log_entity", "entity_type", "entity_id"),
        Index("ix_action_log_undone_created", "is_undone", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_type: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint("action_type IN ('create', 'update', 'delete')"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint("entity_type IN ('task', 'event', 'inbox_item', 'subtask')"),
        nullable=False,
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    is_undone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: utcnow() + timedelta(hours=1)
    )
