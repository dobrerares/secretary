"""Event CRUD operations.

CRUD here is thin: it persists the change and routes the
before/after bookkeeping through the Action seam in `core/actions`.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.actions import log_create, log_delete, log_update, make_snapshot
from secretary.core.schemas import EventCreate, EventFilter, EventUpdate
from secretary.db.models import Event


async def get_event(session: AsyncSession, event_id: int) -> Event | None:
    result = await session.execute(select(Event).where(Event.id == event_id))
    return result.scalar_one_or_none()


async def list_events(session: AsyncSession, filters: EventFilter | None = None) -> list[Event]:
    query = select(Event)

    if filters:
        if filters.area:
            query = query.where(Event.area == filters.area)
        if filters.start_after:
            query = query.where(Event.start_at >= filters.start_after)
        if filters.start_before:
            query = query.where(Event.start_at <= filters.start_before)
        if filters.calendar_source:
            query = query.where(Event.calendar_source == filters.calendar_source)

    query = query.order_by(Event.start_at.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_event(session: AsyncSession, data: EventCreate, batch_id: str) -> Event:
    event = Event(
        title=data.title,
        description=data.description,
        area=data.area,
        start_at=data.start_at,
        end_at=data.end_at,
        location=data.location,
        is_all_day=data.is_all_day,
        calendar_source=data.calendar_source,
        external_id=data.external_id,
        recurrence_rule=data.recurrence_rule,
        inbox_item_id=data.inbox_item_id,
    )
    session.add(event)
    await session.flush()

    await log_create(session, "event", event, batch_id)
    return event


async def update_event(session: AsyncSession, event_id: int, data: EventUpdate, batch_id: str) -> Event | None:
    event = await get_event(session, event_id)
    if not event:
        return None

    before = make_snapshot("event", event)

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(event, key, value)

    await session.flush()

    await log_update(session, "event", before, event, batch_id)
    return event


async def delete_event(session: AsyncSession, event_id: int, batch_id: str) -> bool:
    event = await get_event(session, event_id)
    if not event:
        return False

    await log_delete(session, "event", event, batch_id)
    await session.delete(event)
    await session.flush()
    return True
