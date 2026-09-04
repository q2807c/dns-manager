"""F5 Device management API routes."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, F5Device, Zone
from app.schemas import (
    F5DeviceCreate, F5DeviceUpdate, F5DeviceResponse, F5DeviceListResponse,
)
from app.core.auth import get_current_user, require_permission
from app.services.ssh_connector import ssh_connector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _device_config_from_model(device: F5Device) -> dict:
    """Build a device config dict from a DB model for SSHConnector."""
    return {
        "host": device.host,
        "port": device.port,
        "user": device.username,
        "password": device.password,
        "key_path": device.key_path,
        "key_passphrase": device.key_passphrase,
        "named_conf_path": device.named_conf_path,
        "zone_dir": device.zone_dir,
    }


async def _count_zones_for_device(db: AsyncSession, device_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(Zone).where(Zone.device_id == device_id),
    )
    return result.scalar() or 0


@router.get("", response_model=F5DeviceListResponse)
async def list_devices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all F5 devices."""
    result = await db.execute(select(F5Device).order_by(F5Device.group_name))
    devices = result.scalars().all()

    items = []
    for d in devices:
        items.append(F5DeviceResponse(
            id=d.id,
            group_name=d.group_name,
            host=d.host,
            port=d.port,
            username=d.username,
            key_path=d.key_path,
            named_conf_path=d.named_conf_path,
            zone_dir=d.zone_dir,
            is_active=d.is_active,
            description=d.description,
            zone_count=await _count_zones_for_device(db, d.id),
            created_at=d.created_at,
            updated_at=d.updated_at,
        ))

    return F5DeviceListResponse(items=items, total=len(items))


@router.get("/{device_id}", response_model=F5DeviceResponse)
async def get_device(
    device_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single F5 device."""
    result = await db.execute(select(F5Device).where(F5Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    return F5DeviceResponse(
        id=device.id,
        group_name=device.group_name,
        host=device.host,
        port=device.port,
        username=device.username,
        key_path=device.key_path,
        named_conf_path=device.named_conf_path,
        zone_dir=device.zone_dir,
        is_active=device.is_active,
        description=device.description,
        zone_count=await _count_zones_for_device(db, device.id),
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


@router.post("", response_model=F5DeviceResponse, status_code=201)
async def create_device(
    body: F5DeviceCreate,
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new F5 device (super_admin only)."""
    # Check group_name uniqueness
    existing = await db.execute(
        select(F5Device).where(F5Device.group_name == body.group_name),
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"设备组 '{body.group_name}' 已存在")

    device = F5Device(
        group_name=body.group_name,
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        key_path=body.key_path,
        key_passphrase=body.key_passphrase,
        named_conf_path=body.named_conf_path,
        zone_dir=body.zone_dir,
        is_active=body.is_active,
        description=body.description,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    # Register with SSH connector
    if device.is_active:
        ssh_connector.register_device(device.id, _device_config_from_model(device))

    return F5DeviceResponse(
        id=device.id,
        group_name=device.group_name,
        host=device.host,
        port=device.port,
        username=device.username,
        key_path=device.key_path,
        named_conf_path=device.named_conf_path,
        zone_dir=device.zone_dir,
        is_active=device.is_active,
        description=device.description,
        zone_count=0,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


@router.put("/{device_id}", response_model=F5DeviceResponse)
async def update_device(
    device_id: int,
    body: F5DeviceUpdate,
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """Update an F5 device (super_admin only)."""
    result = await db.execute(select(F5Device).where(F5Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Check group_name uniqueness if changed
    if body.group_name is not None and body.group_name != device.group_name:
        existing = await db.execute(
            select(F5Device).where(F5Device.group_name == body.group_name),
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"设备组 '{body.group_name}' 已存在")

    # Update fields
    update_fields = [
        "group_name", "host", "port", "username", "password",
        "key_path", "key_passphrase", "named_conf_path", "zone_dir",
        "is_active", "description",
    ]
    for field in update_fields:
        value = getattr(body, field, None)
        if value is not None:
            setattr(device, field, value)

    await db.commit()
    await db.refresh(device)

    # Refresh SSH connector registry
    ssh_connector.unregister_device(device.id)
    if device.is_active:
        ssh_connector.register_device(device.id, _device_config_from_model(device))

    return F5DeviceResponse(
        id=device.id,
        group_name=device.group_name,
        host=device.host,
        port=device.port,
        username=device.username,
        key_path=device.key_path,
        named_conf_path=device.named_conf_path,
        zone_dir=device.zone_dir,
        is_active=device.is_active,
        description=device.description,
        zone_count=await _count_zones_for_device(db, device.id),
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


@router.delete("/{device_id}")
async def delete_device(
    device_id: int,
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an F5 device (super_admin only)."""
    result = await db.execute(select(F5Device).where(F5Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Check if zones are still assigned
    zone_count = await _count_zones_for_device(db, device_id)
    if zone_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"设备 '{device.group_name}' 上还有 {zone_count} 个 Zone，请先将 Zone 迁移到其他设备",
        )

    # Unregister from SSH connector
    ssh_connector.unregister_device(device.id)

    await db.delete(device)
    await db.commit()

    return {"status": "success", "device": device.group_name}


@router.post("/{device_id}/test")
async def test_device_connection(
    device_id: int,
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """Test SSH connectivity to an F5 device."""
    result = await db.execute(select(F5Device).where(F5Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        # Register temporarily and test
        ssh_connector.register_device(device.id, _device_config_from_model(device))
        exit_code, stdout, stderr = ssh_connector.exec_command(
            "echo OK && hostname", device_id=device.id,
        )
        ssh_connector.unregister_device(device.id)
        return {
            "status": "success" if exit_code == 0 else "failed",
            "hostname": stdout.strip(),
            "stderr": stderr.strip(),
        }
    except Exception as e:
        ssh_connector.unregister_device(device.id)
        return {"status": "failed", "error": str(e)}
