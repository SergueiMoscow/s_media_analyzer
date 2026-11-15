"""Очередь задач: захват пачки (SKIP LOCKED)."""
from db.connector import AsyncSession
from db.models import MediaAnalysis
from repositories.analysis import claim_tasks as claim_tasks_repo


async def claim(kind: str, limit: int, lock_timeout_sec: int) -> list[MediaAnalysis]:
    """Захватывает задачи вида ``kind`` (FOR UPDATE SKIP LOCKED)."""
    async with AsyncSession() as session:
        return await claim_tasks_repo(session, kind, limit, lock_timeout_sec)
