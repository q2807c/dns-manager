"""Change request approval workflow API routes."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import User, Zone, AuditLog, ChangeRequest
from app.schemas import (
    ChangeRequestResponse, ChangeRequestListResponse,
    ChangeRequestCreate, ChangeRequestReview,
)
from app.core.auth import get_current_user, require_permission
from app.core.rbac import has_permission
from app.services.ssh_connector import ssh_connector
from app.services.zone_parser import (
    parse_zone_text, extract_records, get_zone_serial,
    validate_zone_syntax, increment_serial,
)
from app.services.backup_service import save_backup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/change-requests", tags=["change_requests"])


async def _execute_change(cr: ChangeRequest, db: AsyncSession, reviewer: User):
    """Execute an approved change request on the F5 device."""
    action = cr.action
    zone_name = cr.zone_name
    payload = cr.payload or {}

    try:
        if action == "record_create":
            await _execute_record_create(zone_name, payload, db, reviewer)
        elif action == "record_modify":
            await _execute_record_modify(zone_name, payload, db, reviewer)
        elif action == "record_delete":
            await _execute_record_delete(zone_name, payload, db, reviewer)
        elif action == "zone_create":
            await _execute_zone_create(zone_name, payload, db, reviewer)
        elif action == "zone_delete":
            await _execute_zone_delete(zone_name, db, reviewer)
        elif action == "raw_zone_edit":
            await _execute_raw_zone_edit(zone_name, payload, db, reviewer)
        else:
            raise ValueError(f"Unknown action: {action}")

        cr.executed_at = datetime.now()
        cr.status = "executed"

    except Exception as e:
        logger.error(f"Change execution failed: {e}")
        raise


async def _get_zone_device_id(db, zone_name: str) -> Optional[int]:
    """Look up a zone's device_id."""
    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()
    return zone.device_id if zone else None


async def _execute_record_create(zone_name: str, payload: dict, db, user: User):
    """Execute a record creation on F5."""
    device_id = await _get_zone_device_id(db, zone_name)
    content, backup = ssh_connector.begin_zone_edit(zone_name, device_id=device_id)
    current_serial = get_zone_serial(content)

    # Save backup to DB
    try:
        await save_backup(db, zone_name, content, current_serial, user.id)
    except Exception as e:
        logger.warning(f"Failed to save backup record: {e}")

    new_serial = increment_serial(current_serial)

    from app.api.routes.records import _format_record_line, _update_serial_in_content
    from app.schemas import DNSRecordCreate

    record = DNSRecordCreate(**payload)
    record_line = _format_record_line(record)

    new_content = _update_serial_in_content(content, new_serial)
    new_content = new_content.rstrip() + "\n" + record_line + "\n"

    is_valid, errors = validate_zone_syntax(new_content)
    if not is_valid:
        raise ValueError(f"Invalid zone after change: {'; '.join(errors)}")

    exit_code, out, err = ssh_connector.end_zone_edit(zone_name, new_content, device_id=device_id)
    if exit_code != 0:
        ssh_connector.rollback_zone_edit(zone_name, backup, device_id=device_id)
        raise Exception(f"rndc reload failed: {err}")

    # Update zone metadata
    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()
    if zone:
        zone.last_serial = new_serial

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="record_create", zone_name=zone_name,
        target_record=f"{record.name} {record.type}",
        after_value=record.data,
        status="success",
    ))

    # Refresh record_count from actual zone file
    if zone:
        from app.api.routes.records import _refresh_record_count
        await _refresh_record_count(db, zone, zone_name)


async def _execute_record_modify(zone_name: str, payload: dict, db, user: User):
    """Execute a record modification on F5."""
    from app.api.routes.records import _format_record_line, _update_serial_in_content
    from app.schemas import DNSRecordCreate

    device_id = await _get_zone_device_id(db, zone_name)
    content, backup = ssh_connector.begin_zone_edit(zone_name, device_id=device_id)
    current_serial = get_zone_serial(content)

    # Save backup to DB
    try:
        await save_backup(db, zone_name, content, current_serial, user.id)
    except Exception as e:
        logger.warning(f"Failed to save backup record: {e}")

    new_serial = increment_serial(current_serial)

    record_id = payload.get("record_id", 0)
    zone = parse_zone_text(content, zone_name)
    records = extract_records(zone, zone_name)

    if record_id < 0 or record_id >= len(records):
        raise ValueError("Record not found")

    before = records[record_id]
    new_data = payload.get("data", before.data)
    new_name = payload.get("name", before.name)
    new_type = payload.get("type", before.type)
    new_ttl = payload.get("ttl", before.ttl)

    old_line = _format_record_line(DNSRecordCreate(name=before.name, type=before.type, ttl=before.ttl, data=before.data))
    new_line = _format_record_line(DNSRecordCreate(name=new_name, type=new_type, ttl=new_ttl, data=new_data))

    new_content = content.replace(old_line, new_line)
    new_content = _update_serial_in_content(new_content, new_serial)

    is_valid, errors = validate_zone_syntax(new_content)
    if not is_valid:
        raise ValueError(f"Invalid zone: {'; '.join(errors)}")

    exit_code, out, err = ssh_connector.end_zone_edit(zone_name, new_content, device_id=device_id)
    if exit_code != 0:
        ssh_connector.rollback_zone_edit(zone_name, backup, device_id=device_id)
        raise Exception(f"rndc reload failed: {err}")

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="record_modify", zone_name=zone_name,
        target_record=f"{before.name} {before.type}",
        before_value=f"{before.type} {before.data}",
        after_value=f"{new_type} {new_data}",
        status="success",
    ))

    # Refresh record_count from actual zone file
    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone_obj = result.scalar_one_or_none()
    if zone_obj:
        zone_obj.last_serial = new_serial
        from app.api.routes.records import _refresh_record_count
        await _refresh_record_count(db, zone_obj, zone_name)


async def _execute_record_delete(zone_name: str, payload: dict, db, user: User):
    """Execute a record deletion on F5."""
    from app.api.routes.records import _format_record_line, _update_serial_in_content
    from app.schemas import DNSRecordCreate

    device_id = await _get_zone_device_id(db, zone_name)
    content, backup = ssh_connector.begin_zone_edit(zone_name, device_id=device_id)
    current_serial = get_zone_serial(content)

    # Save backup to DB
    try:
        await save_backup(db, zone_name, content, current_serial, user.id)
    except Exception as e:
        logger.warning(f"Failed to save backup record: {e}")

    new_serial = increment_serial(current_serial)

    record_id = payload.get("record_id", 0)
    zone = parse_zone_text(content, zone_name)
    records = extract_records(zone, zone_name)

    if record_id < 0 or record_id >= len(records):
        raise ValueError("Record not found")

    before = records[record_id]
    old_line = _format_record_line(DNSRecordCreate(name=before.name, type=before.type, ttl=before.ttl, data=before.data))

    new_content = content.replace(old_line + "\n", "").replace(old_line, "")
    new_content = _update_serial_in_content(new_content, new_serial)

    is_valid, errors = validate_zone_syntax(new_content)
    if not is_valid:
        raise ValueError(f"Invalid zone: {'; '.join(errors)}")

    exit_code, out, err = ssh_connector.end_zone_edit(zone_name, new_content, device_id=device_id)
    if exit_code != 0:
        ssh_connector.rollback_zone_edit(zone_name, backup, device_id=device_id)
        raise Exception(f"rndc reload failed: {err}")

    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone_obj = result.scalar_one_or_none()
    if zone_obj:
        zone_obj.last_serial = new_serial
        from app.api.routes.records import _refresh_record_count
        await _refresh_record_count(db, zone_obj, zone_name)

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="record_delete", zone_name=zone_name,
        target_record=f"{before.name} {before.type}",
        before_value=f"{before.type} {before.data}",
        status="success",
    ))


async def _execute_zone_create(zone_name: str, payload: dict, db, user: User):
    """Execute zone creation on F5."""
    from app.services.zone_parser import generate_zone_template

    ttl = payload.get("ttl", 300)
    master = payload.get("master_server", "dns1.cnooc.com.")
    email = payload.get("email_contact", "hostmaster.cnooc.com.")
    ns = payload.get("ns_servers", None)

    content = generate_zone_template(zone_name, ttl, master, email, ns)
    device_id = payload.get("device_id")
    ssh_connector.create_zone(zone_name, content, device_id=device_id)

    soa = ssh_connector.dig_query(f"{zone_name} SOA", device_id=device_id)
    if not soa:
        raise Exception("Zone creation verification failed")

    zone = Zone(
        zone_name=zone_name,
        zone_type="master",
        view_name=payload.get("view_name", "external"),
        file_name=f"db.external.{zone_name}",
        last_serial=increment_serial(None),
        last_modified_by=user.id,
    )
    db.add(zone)

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="zone_create", zone_name=zone_name,
        status="success",
    ))


async def _execute_zone_delete(zone_name: str, db, user: User):
    """Execute zone deletion on F5."""
    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()
    if not zone:
        raise ValueError("Zone not found")

    device_id = zone.device_id
    ssh_connector.delete_zone(zone_name, device_id=device_id)

    verify = ssh_connector.dig_query(f"{zone_name} SOA", device_id=device_id)
    if verify:
        raise Exception("Zone deletion verification failed — zone still resolving")

    zone.is_active = False

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="zone_delete", zone_name=zone_name,
        status="success",
    ))


async def _execute_raw_zone_edit(zone_name: str, payload: dict, db, user: User):
    """Execute raw zone edit on F5."""
    new_content = payload.get("content", "")
    if not new_content:
        raise ValueError("No content provided")

    is_valid, errors = validate_zone_syntax(new_content)
    if not is_valid:
        raise ValueError(f"Invalid zone syntax: {'; '.join(errors)}")

    device_id = await _get_zone_device_id(db, zone_name)
    content, backup = ssh_connector.begin_zone_edit(zone_name, device_id=device_id)

    # Save backup to DB
    try:
        current_serial = get_zone_serial(content)
        await save_backup(db, zone_name, content, current_serial, user.id)
    except Exception as e:
        logger.warning(f"Failed to save backup record: {e}")

    exit_code, out, err = ssh_connector.end_zone_edit(zone_name, new_content, device_id=device_id)
    if exit_code != 0:
        ssh_connector.rollback_zone_edit(zone_name, backup, device_id=device_id)
        raise Exception(f"rndc reload failed: {err}")

    soa = ssh_connector.dig_query(f"{zone_name} SOA", device_id=device_id)
    if not soa:
        ssh_connector.rollback_zone_edit(zone_name, backup, device_id=device_id)
        raise Exception("Zone reload verification failed")

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="raw_zone_update", zone_name=zone_name,
        status="success",
    ))


@router.post("", response_model=ChangeRequestResponse, status_code=201)
async def create_change_request(
    body: ChangeRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a change request for approval."""
    valid_actions = [
        "record_create", "record_modify", "record_delete",
        "zone_create", "zone_delete", "raw_zone_edit",
    ]
    if body.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {', '.join(valid_actions)}")

    cr = ChangeRequest(
        user_id=user.id,
        action=body.action,
        zone_name=body.zone_name,
        payload=body.payload,
        summary=body.summary or f"{body.action} on {body.zone_name}",
        status="pending",
    )
    db.add(cr)
    await db.flush()
    await db.refresh(cr)

    # Load user relationship for response
    await db.refresh(cr, ["user"])

    return ChangeRequestResponse(
        id=cr.id,
        submitted_by=cr.user.username if cr.user else "",
        action=cr.action,
        zone_name=cr.zone_name,
        payload=cr.payload,
        status=cr.status,
        summary=cr.summary,
        submitted_at=cr.submitted_at,
        reviewed_at=None,
        executed_at=None,
        review_comment=None,
        reviewer=None,
    )


@router.get("", response_model=ChangeRequestListResponse)
async def list_change_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    zone_name: Optional[str] = Query(None),
    my_requests: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List change requests. Approvers see all pending; operators see their own."""
    query = select(ChangeRequest).options(
        selectinload(ChangeRequest.user),
        selectinload(ChangeRequest.approver),
    )

    # If user is approver/admin and not filtering "my", show all pending
    is_approver = has_permission(user, "approve_requests")
    if my_requests or not is_approver:
        query = query.where(ChangeRequest.user_id == user.id)

    if status_filter:
        query = query.where(ChangeRequest.status == status_filter)
    if zone_name:
        query = query.where(ChangeRequest.zone_name == zone_name)

    query = query.order_by(ChangeRequest.submitted_at.desc())

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    crs = result.scalars().all()

    items = []
    for cr in crs:
        items.append(ChangeRequestResponse(
            id=cr.id,
            submitted_by=cr.user.username if cr.user else "unknown",
            action=cr.action,
            zone_name=cr.zone_name,
            payload=cr.payload,
            status=cr.status,
            summary=cr.summary,
            submitted_at=cr.submitted_at,
            reviewed_at=cr.reviewed_at,
            executed_at=cr.executed_at,
            review_comment=cr.review_comment,
            reviewer=cr.approver.username if cr.approver else None,
        ))

    return ChangeRequestListResponse(
        items=items, total=total, page=page, page_size=page_size,
    )


@router.get("/{cr_id}", response_model=ChangeRequestResponse)
async def get_change_request(
    cr_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single change request with full details."""
    query = select(ChangeRequest).options(
        selectinload(ChangeRequest.user),
        selectinload(ChangeRequest.approver),
    ).where(ChangeRequest.id == cr_id)

    result = await db.execute(query)
    cr = result.scalar_one_or_none()
    if not cr:
        raise HTTPException(status_code=404, detail="Change request not found")

    # Only submitter, approvers, or admins can view
    is_approver = has_permission(user, "approve_requests")
    if cr.user_id != user.id and not is_approver:
        raise HTTPException(status_code=403, detail="Access denied")

    return ChangeRequestResponse(
        id=cr.id,
        submitted_by=cr.user.username if cr.user else "unknown",
        action=cr.action,
        zone_name=cr.zone_name,
        payload=cr.payload,
        status=cr.status,
        summary=cr.summary,
        submitted_at=cr.submitted_at,
        reviewed_at=cr.reviewed_at,
        executed_at=cr.executed_at,
        review_comment=cr.review_comment,
        reviewer=cr.approver.username if cr.approver else None,
    )


@router.put("/{cr_id}/review", response_model=ChangeRequestResponse)
async def review_change_request(
    cr_id: int,
    body: ChangeRequestReview,
    user: User = Depends(require_permission("approve_requests")),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a change request. Approval triggers execution on F5."""
    query = select(ChangeRequest).options(
        selectinload(ChangeRequest.user),
        selectinload(ChangeRequest.approver),
    ).where(ChangeRequest.id == cr_id)

    result = await db.execute(query)
    cr = result.scalar_one_or_none()
    if not cr:
        raise HTTPException(status_code=404, detail="Change request not found")

    if cr.status != "pending":
        raise HTTPException(status_code=400, detail=f"Change request already {cr.status}")

    cr.approver_id = user.id
    cr.reviewed_at = datetime.now()
    cr.review_comment = body.comment

    if body.action == "reject":
        cr.status = "rejected"
        await db.flush()
        await db.refresh(cr)

        return ChangeRequestResponse(
            id=cr.id,
            submitted_by=cr.user.username if cr.user else "",
            action=cr.action,
            zone_name=cr.zone_name,
            payload=cr.payload,
            status=cr.status,
            summary=cr.summary,
            submitted_at=cr.submitted_at,
            reviewed_at=cr.reviewed_at,
            executed_at=None,
            review_comment=cr.review_comment,
            reviewer=user.username,
        )

    # Approve: mark as approved first, then execute
    cr.status = "approved"

    # Try to execute
    try:
        await _execute_change(cr, db, user)
    except Exception as e:
        cr.status = "execution_failed"
        cr.review_comment = (cr.review_comment or "") + f"\nExecution error: {e}"
        await db.flush()
        await db.refresh(cr)

        return ChangeRequestResponse(
            id=cr.id,
            submitted_by=cr.user.username if cr.user else "",
            action=cr.action,
            zone_name=cr.zone_name,
            payload=cr.payload,
            status=cr.status,
            summary=cr.summary,
            submitted_at=cr.submitted_at,
            reviewed_at=cr.reviewed_at,
            executed_at=None,
            review_comment=cr.review_comment,
            reviewer=user.username,
        )

    await db.flush()
    await db.refresh(cr)

    return ChangeRequestResponse(
        id=cr.id,
        submitted_by=cr.user.username if cr.user else "",
        action=cr.action,
        zone_name=cr.zone_name,
        payload=cr.payload,
        status=cr.status,
        summary=cr.summary,
        submitted_at=cr.submitted_at,
        reviewed_at=cr.reviewed_at,
        executed_at=cr.executed_at,
        review_comment=cr.review_comment,
        reviewer=user.username,
    )
