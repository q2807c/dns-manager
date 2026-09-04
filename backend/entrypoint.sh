#!/bin/bash
set -e

echo "=== DNS Zone Manager — Backend Entrypoint ==="
echo "Mode: ${DEPLOY_MODE:-lite}"

# ── Wait for PostgreSQL (Full mode only) ──
if [ "${USE_SQLITE:-true}" != "true" ]; then
    echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}..."
    until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" \
            -U "${POSTGRES_USER:-dns_admin}" -d "${POSTGRES_DB:-dns_manager}" 2>/dev/null; do
        sleep 2
    done
    echo "PostgreSQL is ready."
fi

# ── SQLite DB path ──
if [ "${USE_SQLITE:-true}" = "true" ]; then
    export SQLITE_DB_PATH="${SQLITE_DB_PATH:-/app/data/dns_manager.db}"
    echo "Using SQLite: $SQLITE_DB_PATH"
fi

# ── Run database migrations / seed if needed ──
echo "Running database initialization..."
python -c "
import asyncio
from app.database import engine, Base
# Import all models so Base.metadata knows about every table
from app.models import User, Zone, AuditLog, UserZoneAccess, F5Device, ChangeRequest, ZoneBackup  # noqa: F401

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Database tables ensured.')

asyncio.run(init_db())
"

# Check if seed data needed (only seed if no users exist)
python -c "
import asyncio
from sqlalchemy import select, func
from app.database import async_session_factory as async_session
from app.models import User

async def check_and_seed():
    async with async_session() as db:
        result = await db.execute(select(func.count()).select_from(User))
        count = result.scalar()
        if count == 0:
            print('No users found. Seeding default data...')
            import subprocess
            subprocess.run(['python', 'seed.py'], check=True)
        else:
            print(f'Found {count} user(s). Skipping seed.')

asyncio.run(check_and_seed())
"

echo "=== Starting application ==="
exec "$@"
