from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from takt.time_accounting.models import User


class AccessDenied(PermissionError):
    pass


async def load_actor(session: AsyncSession, actor_id: UUID, *, lock: bool = False) -> User:
    query = select(User).where(User.id == actor_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    actor = await session.scalar(query)
    if actor is None or not actor.is_active:
        raise AccessDenied("The account does not have access.")
    return actor
