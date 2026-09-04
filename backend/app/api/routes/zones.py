"""Zone management API routes."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Zone, AuditLog, F5Device
from app.schemas import (
    ZoneResponse, ZoneListResponse, ZoneCreateRequest,
    RawZoneResponse, RawZoneUpdate, ZoneSyncResponse, ZoneSyncItem,
)
from app.core.auth import get_current_user, require_permission
from app.core.rbac import has_permission, has_permission_for_zone
from app.services.ssh_connector import ssh_connector
from app.services.zone_parser import (
    parse_zone_text, extract_records, get_zone_serial,
    validate_zone_syntax, generate_zone_template, increment_serial,
)
from app.services.backup_service import save_backup
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zones", tags=["zones"])


@router.post("/sync", response_model=ZoneSyncResponse)
async def sync_zones_from_devices(
    device_id: Optional[int] = Query(None, description="指定设备 ID；不传则同步所有活跃设备"),
    user: User = Depends(require_permission("zone_create")),
    db: AsyncSession = Depends(get_db),
):
    """从 F5 设备 named.conf 同步 Zone 列表到本地数据库。"""
    response = ZoneSyncResponse()

    # Find target devices
    query = select(F5Device)
    if device_id is not None:
        query = query.where(F5Device.id == device_id)
    else:
        query = query.where(F5Device.is_active == True)
    result = await db.execute(query)
    devices = result.scalars().all()

    if not devices:
        raise HTTPException(status_code=404, detail="未找到活跃的 F5 设备")

    # Get all existing zone names in DB
    existing_result = await db.execute(select(Zone.zone_name))
    existing_zones = set(row[0] for row in existing_result.fetchall())

    for device in devices:
        logger.info(f"Syncing zones from {device.group_name} ({device.host})...")

        # Ensure device is registered in SSH pool
        ssh_connector.register_device(
            device.id, {
                "host": device.host,
                "port": device.port or 22,
                "user": device.username or "root",
                "password": device.password,
                "key_path": device.key_path,
                "key_passphrase": device.key_passphrase,
                "named_conf_path": device.named_conf_path,
                "zone_dir": device.zone_dir,
            }
        )

        try:
            zones_on_f5 = ssh_connector.discover_zones(device_id=device.id)
        except Exception as e:
            logger.error(f"Failed to discover zones on {device.group_name}: {e}")
            response.items.append(ZoneSyncItem(
                zone_name=f"*{device.group_name}",
                device_group=device.group_name,
                status="error",
                detail=f"SSH 连接失败: {e}",
            ))
            response.errors += 1
            continue

        for zone_name in zones_on_f5:
            # Determine record count from zone content
            record_count = 0
            try:
                content = ssh_connector.read_zone(zone_name, device_id=device.id)
                zone_obj = parse_zone_text(content, zone_name)
                records = extract_records(zone_obj, zone_name)
                record_count = len(records)
            except Exception:
                pass  # skip record count if read fails

            if zone_name in existing_zones:
                # Update record_count for existing zone
                existing_zone = (await db.execute(
                    select(Zone).where(Zone.zone_name == zone_name)
                )).scalar_one_or_none()
                if existing_zone and existing_zone.record_count != record_count:
                    existing_zone.record_count = record_count
                    response.items.append(ZoneSyncItem(
                        zone_name=zone_name,
                        device_group=device.group_name,
                        status="updated",
                        detail=f"record_count {existing_zone.record_count} → {record_count}",
                    ))
                    response.updated += 1
                response.already_exists += 1
                continue

            zone_entry = Zone(
                zone_name=zone_name,
                zone_type="master",
                view_name="external",
                file_name=f"db.external.{zone_name}",
                record_count=record_count,
                last_serial=None,
                last_modified_by=user.id,
                device_id=device.id,
            )
            db.add(zone_entry)
            existing_zones.add(zone_name)
            response.synced += 1
            response.items.append(ZoneSyncItem(
                zone_name=zone_name,
                device_group=device.group_name,
                status="created",
                detail=f"{record_count} records",
            ))

        response.total += len(zones_on_f5)

    await db.commit()

    logger.info(
        f"Zone sync complete: {response.synced} created, "
        f"{response.already_exists} existed, {response.errors} errors"
    )
    return response


@router.get("", response_model=ZoneListResponse)
async def list_zones(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None),
    view_name: Optional[str] = Query(None),
    user: User = Depends(require_permission("zone_view")),
    db: AsyncSession = Depends(get_db),
):
    """List all accessible zones with pagination."""
    query = select(Zone)

    # super_admin sees all; others see assigned zones
    if user.role != "super_admin":
        accessible = [a.zone_id for a in user.zone_access if a.zone_id]
        if not accessible:
            return ZoneListResponse(items=[], total=0, page=page, page_size=page_size)
        query = query.where(Zone.id.in_(accessible))

    if search:
        query = query.where(Zone.zone_name.ilike(f"%{search}%"))
    if view_name:
        query = query.where(Zone.view_name == view_name)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(Zone.zone_name).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    zones = result.scalars().all()

    # Refresh record_count from F5 for each zone (real-time, not cached)
    for z in zones:
        try:
            content = ssh_connector.read_zone(z.zone_name, device_id=z.device_id)
            parsed = parse_zone_text(content, z.zone_name)
            records = extract_records(parsed, z.zone_name)
            live_count = len(records)
            if z.record_count != live_count:
                z.record_count = live_count
        except Exception as e:
            logger.debug(f"Could not refresh record_count for {z.zone_name}: {e}")
    await db.flush()

    return ZoneListResponse(
        items=[ZoneResponse.model_validate(z) for z in zones],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{zone_name}", response_model=ZoneResponse)
async def get_zone(
    zone_name: str,
    user: User = Depends(require_permission("zone_view")),
    db: AsyncSession = Depends(get_db),
):
    """Get zone details."""
    if not has_permission_for_zone(user, zone_name, "zone_view"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    return ZoneResponse.model_validate(zone)


@router.get("/{zone_name}/raw", response_model=RawZoneResponse)
async def get_raw_zone(
    zone_name: str,
    user: User = Depends(require_permission("zone_view")),
    db: AsyncSession = Depends(get_db),
):
    """Get raw zone file content from F5."""
    if not has_permission_for_zone(user, zone_name, "zone_view"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()

    try:
        content = ssh_connector.read_zone(zone_name, device_id=zone.device_id if zone else None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SSH read failed: {e}")

    serial = get_zone_serial(content)
    return RawZoneResponse(zone_name=zone_name, content=content, serial=serial)


@router.put("/{zone_name}/raw")
async def update_raw_zone(
    zone_name: str,
    body: RawZoneUpdate,
    user: User = Depends(require_permission("raw_zone_edit")),
    db: AsyncSession = Depends(get_db),
):
    """Update raw zone file content (admin only)."""
    if not has_permission_for_zone(user, zone_name, "raw_zone_edit"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    # Validate syntax
    is_valid, errors = validate_zone_syntax(body.content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid zone syntax: {'; '.join(errors)}")

    # Full proper workflow: sync journal → backup → write → reload
    backup = None
    try:
        # Step 1: sync journal & backup (begin_zone_edit handles this)
        content, backup = ssh_connector.begin_zone_edit(zone_name, device_id=zone.device_id)

        # Save backup to DB
        try:
            current_serial = get_zone_serial(content)
            await save_backup(db, zone_name, content, current_serial, user.id)
            await db.flush()
        except Exception as e:
            logger.warning(f"Failed to save backup record: {e}")

        # Step 2: write new content & reload
        exit_code, out, err = ssh_connector.end_zone_edit(zone_name, body.content, device_id=zone.device_id)
        if exit_code != 0:
            raise Exception(f"rndc reload failed: {err}")

        # Step 3: verify
        soa = ssh_connector.dig_query(f"{zone_name} SOA", device_id=zone.device_id)
        if not soa:
            raise Exception("Zone reload verification failed — no SOA returned")

    except Exception as e:
        # Rollback on failure
        if backup:
            try:
                ssh_connector.rollback_zone_edit(zone_name, backup, device_id=zone.device_id)
            except Exception as rollback_err:
                logger.error(f"Rollback failed: {rollback_err}")

        db.add(AuditLog(
            user_id=user.id, username=user.username,
            action="raw_zone_update", zone_name=zone_name,
            status="failed", ssh_output=str(e),
        ))
        await db.flush()
        raise HTTPException(status_code=500, detail=str(e))

    # Log audit
    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="raw_zone_update", zone_name=zone_name,
        status="success",
    ))

    return {"status": "success", "zone": zone_name}


@router.post("", response_model=ZoneResponse, status_code=201)
async def create_zone(
    body: ZoneCreateRequest,
    user: User = Depends(require_permission("zone_create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new DNS zone."""
    # Validate master IP is provided when master server is within the zone
    master = body.master_server.rstrip(".")
    zone = body.zone_name.rstrip(".")
    if master.endswith(f".{zone}") or master == zone:
        if not body.a_record_ip:
            raise HTTPException(
                status_code=400,
                detail=f"主服务器 '{body.master_server}' 属于该 Zone 内部，必须提供主服务器 IP 地址（A 记录）",
            )

    # Generate zone file content
    content = generate_zone_template(
        zone_name=body.zone_name,
        ttl=body.ttl,
        master_server=body.master_server,
        email_contact=body.email_contact,
        ns_servers=body.ns_servers or None,
        master_ip=body.a_record_ip,
    )

    zone_file = f"{settings.F5_ZONE_DIR}/db.external.{body.zone_name}"

    try:
        # Create zone on F5 device (includes syntax check + reload + dig verification)
        ssh_connector.create_zone(body.zone_name, content, device_id=body.device_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Zone creation failed: {e}")

    # Count records in generated content
    zone_parsed = parse_zone_text(content, body.zone_name)
    zone_records = extract_records(zone_parsed, body.zone_name)
    record_count = len(zone_records)

    # Save to database
    zone_obj = Zone(
        zone_name=body.zone_name,
        zone_type="master",
        view_name=body.view_name,
        file_name=f"db.external.{body.zone_name}",
        record_count=record_count,
        last_serial=increment_serial(None),
        last_modified_by=user.id,
        device_id=body.device_id,
    )
    db.add(zone_obj)
    await db.commit()
    await db.refresh(zone_obj)

    # Log audit
    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="zone_create", zone_name=body.zone_name,
        status="success",
    ))
    await db.commit()

    return ZoneResponse.model_validate(zone_obj)


@router.delete("/{zone_name}")
async def delete_zone(
    zone_name: str,
    user: User = Depends(require_permission("zone_delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a DNS zone."""
    if not has_permission_for_zone(user, zone_name, "zone_delete"):
        raise HTTPException(status_code=403, detail="Access denied for this zone")

    # Find zone in DB
    result = await db.execute(select(Zone).where(Zone.zone_name == zone_name))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    try:
        ssh_connector.delete_zone(zone_name, device_id=zone.device_id)

        # Verify deletion
        verify_result = ssh_connector.dig_query(f"{zone_name} SOA", device_id=zone.device_id)
        if verify_result:
            raise HTTPException(status_code=500, detail="Zone deletion verification failed — zone still resolving")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Zone deletion failed: {e}")

    zone.is_active = False
    await db.flush()

    return {"status": "success", "zone": zone_name}
