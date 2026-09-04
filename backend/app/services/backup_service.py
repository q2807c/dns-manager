"""Zone backup persistence helpers.

Each zone edit operation records a backup in the ZoneBackup table.
Only the latest backup is kept per zone — old records are pruned on each new backup.
"""

import logging
from sqlalchemy import select, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ZoneBackup

logger = logging.getLogger(__name__)


async def save_backup(
    db: AsyncSession,
    zone_name: str,
    content: str,
    serial: str | None,
    user_id: int,
) -> ZoneBackup:
    """Save a backup record and prune old backups for this zone.

    Keeps only the most recent backup per zone.
    """
    # Create new backup
    backup = ZoneBackup(
        zone_name=zone_name,
        content=content,
        serial=serial,
        backed_up_by=user_id,
        backup_type="pre_change",
    )
    db.add(backup)
    await db.flush()

    # Delete older backups for this zone (keep only the latest)
    old_backups = await db.execute(
        select(ZoneBackup.id)
        .where(
            ZoneBackup.zone_name == zone_name,
            ZoneBackup.id != backup.id,
        )
        .order_by(desc(ZoneBackup.created_at))
    )
    old_ids = [row[0] for row in old_backups.all()]
    if old_ids:
        await db.execute(
            delete(ZoneBackup).where(ZoneBackup.id.in_(old_ids))
        )
        await db.flush()
        logger.info(f"Pruned {len(old_ids)} old backup(s) for {zone_name}")

    logger.info(f"Backup saved for {zone_name} (id={backup.id})")
    return backup
