"""Audit and backup API routes."""
from typing import Optional
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, AuditLog, ZoneBackup
from app.schemas import (
    AuditLogResponse, AuditListResponse,
    ZoneBackupResponse, ZoneBackupDetailResponse,
)
from app.core.auth import get_current_user, require_permission
from app.core.rbac import has_permission_for_zone

router = APIRouter(tags=["audit"])


# ── Audit Log ──

@router.get("/api/audit", response_model=AuditListResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    zone_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user: User = Depends(require_permission("view_audit")),
    db: AsyncSession = Depends(get_db),
):
    """List audit logs with filters."""
    query = select(AuditLog)

    if username:
        query = query.where(AuditLog.username.ilike(f"%{username}%"))
    if action:
        query = query.where(AuditLog.action == action)
    if zone_name:
        query = query.where(AuditLog.zone_name.ilike(f"%{zone_name}%"))
    if status:
        query = query.where(AuditLog.status == status)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(desc(AuditLog.timestamp)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return AuditListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/audit/export")
async def export_audit_logs(
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    zone_name: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: User = Depends(require_permission("view_audit")),
    db: AsyncSession = Depends(get_db),
):
    """Export audit logs as CSV."""
    query = select(AuditLog)

    if username:
        query = query.where(AuditLog.username.ilike(f"%{username}%"))
    if action:
        query = query.where(AuditLog.action == action)
    if zone_name:
        query = query.where(AuditLog.zone_name.ilike(f"%{zone_name}%"))
    if start_date:
        query = query.where(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.where(AuditLog.timestamp <= f"{end_date} 23:59:59")

    query = query.order_by(desc(AuditLog.timestamp)).limit(10000)
    result = await db.execute(query)
    logs = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "User", "Action", "Zone", "Target Record", "Before", "After", "Status", "Timestamp"])
    for log in logs:
        writer.writerow([
            log.id, log.username, log.action, log.zone_name,
            log.target_record, log.before_value, log.after_value,
            log.status, log.timestamp.isoformat() if log.timestamp else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
    )


# ── Backups ──

@router.get("/api/zones/{zone_name}/backups", response_model=list[ZoneBackupResponse])
async def list_backups(
    zone_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List backups for a zone."""
    if not has_permission_for_zone(user, zone_name, "zone_view"):
        raise HTTPException(status_code=403, detail="Access denied")

    query = (
        select(ZoneBackup)
        .where(ZoneBackup.zone_name == zone_name)
        .order_by(desc(ZoneBackup.created_at))
        .limit(50)
    )
    result = await db.execute(query)
    backups = result.scalars().all()

    return [ZoneBackupResponse.model_validate(b) for b in backups]


@router.get("/api/zones/{zone_name}/backups/{backup_id}", response_model=ZoneBackupDetailResponse)
async def get_backup_detail(
    zone_name: str,
    backup_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full content of a specific backup."""
    if not has_permission_for_zone(user, zone_name, "zone_view"):
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(ZoneBackup).where(
            ZoneBackup.id == backup_id,
            ZoneBackup.zone_name == zone_name,
        )
    )
    backup = result.scalar_one_or_none()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")

    return ZoneBackupDetailResponse.model_validate(backup)
