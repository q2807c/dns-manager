"""User management API routes (admin only)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import User, UserZoneAccess
from app.schemas import UserResponse, UserCreate, UserUpdate
from app.core.auth import get_current_user, require_permission, hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


def _build_zone_access_response(user: User) -> list[dict]:
    """Build zone_access list from User.zone_access relationship."""
    if not user.zone_access:
        return []
    result = []
    for za in user.zone_access:
        entry = {
            "zone_id": za.zone_id,
            "zone_pattern": za.zone_pattern,
            "permissions": za.permissions or [],
        }
        result.append(entry)
    return result


async def _sync_zone_access(db: AsyncSession, user: User, entries: list[dict]):
    """Delete old UserZoneAccess rows and create new ones."""
    # Delete existing
    await db.execute(
        delete(UserZoneAccess).where(UserZoneAccess.user_id == user.id)
    )

    # Create new entries
    for entry in entries:
        za = UserZoneAccess(
            user_id=user.id,
            zone_id=entry.get("zone_id"),
            zone_pattern=entry.get("zone_pattern"),
            permissions=entry.get("permissions", []),
        )
        db.add(za)


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """List all users (super_admin only)."""
    count_query = select(func.count()).select_from(select(User).subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = (
        select(User)
        .options(selectinload(User.zone_access))
        .order_by(User.username)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    users = result.scalars().all()

    items = []
    for u in users:
        d = UserResponse.model_validate(u).model_dump()
        d["zone_access"] = _build_zone_access_response(u)
        items.append(d)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=dict, status_code=201)
async def create_user(
    body: UserCreate,
    user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user."""
    # Check duplicate
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        email=body.email,
        role=body.role,
    )
    db.add(new_user)
    await db.flush()

    # Create zone access entries
    if body.zone_access:
        await _sync_zone_access(db, new_user, [za.model_dump() for za in body.zone_access])
        await db.flush()
        # Reload to populate relationships
        result = await db.execute(
            select(User)
            .where(User.id == new_user.id)
            .options(selectinload(User.zone_access))
        )
        new_user = result.scalar_one()

    d = UserResponse.model_validate(new_user).model_dump()
    d["zone_access"] = _build_zone_access_response(new_user)
    return d


@router.put("/{user_id}", response_model=dict)
async def update_user(
    user_id: int,
    body: UserUpdate,
    operator: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """Update a user."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.zone_access))
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if body.display_name is not None:
        target.display_name = body.display_name
    if body.email is not None:
        target.email = body.email
    if body.role is not None:
        target.role = body.role
    if body.is_active is not None:
        target.is_active = body.is_active
    await db.flush()

    # Sync zone access if provided
    if body.zone_access is not None:
        await _sync_zone_access(db, target, [za.model_dump() for za in body.zone_access])
        await db.flush()
        # Reload
        result = await db.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.zone_access))
        )
        target = result.scalar_one()

    d = UserResponse.model_validate(target).model_dump()
    d["zone_access"] = _build_zone_access_response(target)
    return d


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    operator: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user."""
    if user_id == operator.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_active = False
    await db.flush()
    return {"status": "success", "message": f"User {target.username} disabled"}
