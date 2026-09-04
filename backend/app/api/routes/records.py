"""DNS Record management API routes."""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Zone, AuditLog
from app.schemas import (
    DNSRecordResponse, RecordListResponse,
    DNSRecordCreate, DNSRecordUpdate, DNSRecord,
)
from app.core.auth import get_current_user, require_permission
from app.core.rbac import has_permission_for_zone
from app.services.ssh_connector import ssh_connector
from app.services.zone_parser import (
    parse_zone_text, extract_records, get_zone_serial,
    validate_zone_syntax, increment_serial, serialize_zone,
)
from app.services.backup_service import save_backup
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zones/{zone_name}/records", tags=["records"])


async def _get_zone(db: AsyncSession, zone_name: str) -> Zone:
    """Look up zone by name, raise 404 if not found."""
    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone


@router.get("", response_model=RecordListResponse)
async def list_records(
    zone_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    record_type: Optional[str] = Query(None),
    user: User = Depends(require_permission("record_view")),
    db: AsyncSession = Depends(get_db),
):
    """List DNS records for a zone."""
    if not has_permission_for_zone(user, zone_name, "record_view"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    zone = await _get_zone(db, zone_name)

    try:
        content = ssh_connector.read_zone(zone_name, device_id=zone.device_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SSH read failed: {e}")

    parsed_zone = parse_zone_text(content, zone_name)
    records = extract_records(parsed_zone, zone_name)

    # Tag with global index BEFORE filtering
    all_records = [(i, r) for i, r in enumerate(records)]

    # Apply filters (preserve global index)
    if record_type:
        all_records = [(i, r) for i, r in all_records if r.type.upper() == record_type.upper()]
    if search:
        search_lower = search.lower()
        all_records = [(i, r) for i, r in all_records if search_lower in r.name.lower() or search_lower in r.data.lower()]

    total = len(all_records)

    # Apply pagination
    start = (page - 1) * page_size
    end = start + page_size
    page_items = all_records[start:end]

    serial = get_zone_serial(content)

    return RecordListResponse(
        items=[DNSRecordResponse(id=global_id, **r.model_dump()) for global_id, r in page_items],
        total=total,
        page=page,
        page_size=page_size,
        zone_name=zone_name,
        zone_serial=serial,
    )


async def _begin_edit(zone_name: str, user: User, db: AsyncSession, device_id: Optional[int] = None):
    """Begin zone edit: sync journal, backup, read content, bump serial."""
    try:
        content, backup = ssh_connector.begin_zone_edit(zone_name, device_id=device_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to begin zone edit: {e}")

    current_serial = get_zone_serial(content)
    new_serial = increment_serial(current_serial)

    # Save backup to DB
    try:
        await save_backup(db, zone_name, content, current_serial, user.id)
        await db.flush()
    except Exception as e:
        logger.warning(f"Failed to save backup record: {e}")

    return content, backup, new_serial


def _commit_edit(zone_name: str, backup: str, new_content: str, device_id: Optional[int] = None):
    """Commit zone edit: write, reload, verify. Rollback on failure."""
    try:
        exit_code, out, err = ssh_connector.end_zone_edit(
            zone_name, new_content, device_id=device_id,
        )
        if exit_code != 0:
            raise Exception(f"rndc reload failed: {err}")
    except Exception as e:
        try:
            ssh_connector.rollback_zone_edit(zone_name, backup, device_id=device_id)
        except Exception as rollback_err:
            logger.error(f"Rollback also failed: {rollback_err}")
        raise HTTPException(status_code=500, detail=f"Zone edit failed: {e}")


@router.post("", response_model=DNSRecordResponse, status_code=201)
async def create_record(
    zone_name: str,
    body: DNSRecordCreate,
    user: User = Depends(require_permission("record_add")),
    db: AsyncSession = Depends(get_db),
):
    """Add a new DNS record to a zone."""
    if not has_permission_for_zone(user, zone_name, "record_add"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    zone = await _get_zone(db, zone_name)
    device_id = zone.device_id

    try:
        content, backup, new_serial = await _begin_edit(zone_name, user, db, device_id=device_id)
    except HTTPException:
        raise

    # Build record line
    record_line = _format_record_line(body)

    # Append record and update serial
    new_content = _update_serial_in_content(content, new_serial)
    new_content = new_content.rstrip() + "\n" + record_line + "\n"

    # Validate
    is_valid, errors = validate_zone_syntax(new_content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid record: {'; '.join(errors)}")

    _commit_edit(zone_name, backup, new_content, device_id=device_id)

    # Audit
    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="record_create", zone_name=zone_name,
        target_record=f"{body.name} {body.type}",
        after_value=body.data,
        status="success",
    ))
    await db.flush()

    # Refresh record_count from actual zone file
    await _refresh_record_count(db, zone, zone_name)

    return DNSRecordResponse(id=0, name=body.name, type=body.type, ttl=body.ttl, data=body.data)


@router.put("/{record_id}")
async def update_record(
    zone_name: str,
    record_id: int,
    body: DNSRecordUpdate,
    user: User = Depends(require_permission("record_modify")),
    db: AsyncSession = Depends(get_db),
):
    """Modify an existing DNS record (by ID/index)."""
    if not has_permission_for_zone(user, zone_name, "record_modify"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    zone = await _get_zone(db, zone_name)
    device_id = zone.device_id

    try:
        content, backup, new_serial = await _begin_edit(zone_name, user, db, device_id=device_id)
    except HTTPException:
        raise

    parsed_zone = parse_zone_text(content, zone_name)
    records = extract_records(parsed_zone, zone_name)

    if record_id < 0 or record_id >= len(records):
        raise HTTPException(status_code=404, detail="Record not found")

    before = records[record_id]
    new_record = DNSRecord(
        name=body.name or before.name,
        type=body.type or before.type,
        ttl=body.ttl or before.ttl,
        data=body.data or before.data,
    )

    # Replace record line
    old_line = _format_record_line(DNSRecordCreate(
        name=before.name, type=before.type, ttl=before.ttl, data=before.data,
    ))
    new_line = _format_record_line(DNSRecordCreate(
        name=new_record.name, type=new_record.type, ttl=new_record.ttl, data=new_record.data,
    ))

    new_content = content.replace(old_line, new_line)
    new_content = _update_serial_in_content(new_content, new_serial)

    # Validate
    is_valid, errors = validate_zone_syntax(new_content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid zone: {'; '.join(errors)}")

    _commit_edit(zone_name, backup, new_content, device_id=device_id)

    # Audit
    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="record_modify", zone_name=zone_name,
        target_record=f"{before.name} {before.type}",
        before_value=f"{before.type} {before.data}",
        after_value=f"{new_record.type} {new_record.data}",
        status="success",
    ))
    await db.flush()

    # Refresh record_count from actual zone file
    await _refresh_record_count(db, zone, zone_name)

    return {"status": "success"}


@router.delete("/{record_id}")
async def delete_record(
    zone_name: str,
    record_id: int,
    user: User = Depends(require_permission("record_delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a DNS record from a zone."""
    if not has_permission_for_zone(user, zone_name, "record_delete"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    zone = await _get_zone(db, zone_name)
    device_id = zone.device_id

    try:
        content, backup, new_serial = await _begin_edit(zone_name, user, db, device_id=device_id)
    except HTTPException:
        raise

    parsed_zone = parse_zone_text(content, zone_name)
    records = extract_records(parsed_zone, zone_name)

    if record_id < 0 or record_id >= len(records):
        raise HTTPException(status_code=404, detail="Record not found")

    before = records[record_id]

    old_line = _format_record_line(DNSRecordCreate(
        name=before.name, type=before.type, ttl=before.ttl, data=before.data,
    ))

    new_content = content.replace(old_line + "\n", "").replace(old_line, "")
    new_content = _update_serial_in_content(new_content, new_serial)

    _commit_edit(zone_name, backup, new_content, device_id=device_id)

    # Audit
    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="record_delete", zone_name=zone_name,
        target_record=f"{before.name} {before.type}",
        before_value=f"{before.type} {before.data}",
        status="success",
    ))
    await db.flush()

    # Refresh record_count from actual zone file
    await _refresh_record_count(db, zone, zone_name)

    return {"status": "success"}


def _format_record_line(record: DNSRecordCreate) -> str:
    """Format a DNS record as a zone file line."""
    name = record.name if record.name != "@" else "@"

    if record.type.upper() == "A":
        return f"{name}  {record.ttl}  IN  A     {record.data}"
    elif record.type.upper() == "AAAA":
        return f"{name}  {record.ttl}  IN  AAAA  {record.data}"
    elif record.type.upper() == "CNAME":
        return f"{name}  {record.ttl}  IN  CNAME {record.data}."
    elif record.type.upper() == "MX":
        priority = record.priority or 10
        return f"{name}  {record.ttl}  IN  MX    {priority} {record.data}."
    elif record.type.upper() == "NS":
        return f"{name}  {record.ttl}  IN  NS    {record.data}."
    elif record.type.upper() == "TXT":
        return f'{name}  {record.ttl}  IN  TXT   "{record.data}"'
    elif record.type.upper() == "PTR":
        return f"{name}  {record.ttl}  IN  PTR   {record.data}."
    elif record.type.upper() == "SRV":
        p = record.priority or 0
        w = record.weight or 0
        pt = record.port or 0
        return f"{name}  {record.ttl}  IN  SRV   {p} {w} {pt} {record.data}."
    else:
        return f"{name}  {record.ttl}  IN  {record.type}  {record.data}"


def _update_serial_in_content(content: str, new_serial: str) -> str:
    """Update the serial number in zone file content."""
    pattern = r"(\d{10,12})\s*;?\s*(serial|Serial|SERIAL)?"
    return re.sub(pattern, f"{new_serial}    ; serial", content, count=1)


async def _refresh_record_count(db: AsyncSession, zone: Zone, zone_name: str):
    """Re-parse the zone file and update record_count in DB."""
    try:
        content = ssh_connector.read_zone(zone_name, device_id=zone.device_id)
        parsed = parse_zone_text(content, zone_name)
        records = extract_records(parsed, zone_name)
        zone.record_count = len(records)
        await db.flush()
    except Exception as e:
        logger.warning(f"Failed to refresh record_count for {zone_name}: {e}")
