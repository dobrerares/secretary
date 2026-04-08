"""Inbox item operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.schemas import InboxItemCreate
from secretary.db.models import InboxItem


async def create_inbox_item(
    session: AsyncSession, data: InboxItemCreate, batch_id: str | None = None
) -> InboxItem:
    item = InboxItem(
        raw_text=data.raw_text,
        source=data.source,
        batch_id=batch_id,
    )
    session.add(item)
    await session.flush()
    return item


async def list_pending(session: AsyncSession) -> list[InboxItem]:
    result = await session.execute(
        select(InboxItem)
        .where(InboxItem.status.in_(["pending", "proposed"]))
        .order_by(InboxItem.created_at.asc())
    )
    return list(result.scalars().all())


async def get_inbox_item(session: AsyncSession, item_id: int) -> InboxItem | None:
    result = await session.execute(select(InboxItem).where(InboxItem.id == item_id))
    return result.scalar_one_or_none()


async def update_proposed_actions(
    session: AsyncSession, item_id: int, proposed_actions: list[dict]
) -> InboxItem | None:
    item = await get_inbox_item(session, item_id)
    if not item:
        return None
    item.proposed_actions = proposed_actions
    item.status = "proposed"
    await session.flush()
    return item


async def process_inbox_item(session: AsyncSession, item_id: int) -> InboxItem | None:
    item = await get_inbox_item(session, item_id)
    if not item:
        return None
    item.status = "processed"
    await session.flush()
    return item


async def reject_inbox_item(session: AsyncSession, item_id: int) -> InboxItem | None:
    item = await get_inbox_item(session, item_id)
    if not item:
        return None
    item.status = "rejected"
    await session.flush()
    return item
