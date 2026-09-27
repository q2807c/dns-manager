"""Initialize SQLite database for VM (non-Docker) deployment.

Mirrors backend/entrypoint.sh logic: create tables, then seed default
data only when no users exist. Run with backend venv python from the
backend/ directory; environment comes from systemd EnvironmentFile.
"""
import asyncio
import subprocess
import sys

from sqlalchemy import func, select

from app.database import async_session_factory, engine, Base
from app.models import (  # noqa: F401
    AuditLog,
    ChangeRequest,
    F5Device,
    User,
    UserZoneAccess,
    Zone,
    ZoneBackup,
)


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables ensured.")

    async with async_session_factory() as db:
        result = await db.execute(select(func.count()).select_from(User))
        count = result.scalar()

    if count == 0:
        print("No users found. Seeding default data...")
        subprocess.run([sys.executable, "seed.py"], check=True)
    else:
        print(f"Found {count} user(s). Skipping seed.")


if __name__ == "__main__":
    asyncio.run(main())
