"""RBAC authorization engine."""
from typing import List, Optional
from app.models import User, UserZoneAccess


ROLE_HIERARCHY = {
    "super_admin": 100,
    "zone_admin": 80,
    "zone_operator": 60,
    "approver": 40,
    "zone_viewer": 20,
}

# Permission matrix by role (default permissions)
ROLE_PERMISSIONS = {
    "super_admin": [
        "zone_view", "zone_create", "zone_delete", "zone_modify",
        "record_add", "record_modify", "record_delete", "record_view",
        "raw_zone_edit", "approve_requests", "view_audit", "manage_users",
    ],
    "zone_admin": [
        "zone_view", "zone_create", "zone_delete",
        "record_add", "record_modify", "record_delete", "record_view",
        "raw_zone_edit", "approve_requests", "view_audit",
    ],
    "zone_operator": [
        "zone_view",
        "record_add", "record_modify", "record_delete", "record_view",
    ],
    "zone_viewer": [
        "zone_view", "record_view",
    ],
    "approver": [
        "zone_view", "record_view", "approve_requests",
    ],
}


def has_permission(user: User, permission: str) -> bool:
    """Check if user has a specific permission by role."""
    if not user or not user.is_active:
        return False
    role_perms = ROLE_PERMISSIONS.get(user.role, [])
    return permission in role_perms


def has_permission_for_zone(user: User, zone_name: str, permission: str) -> bool:
    """Check if user has permission for a specific zone.

    super_admin bypasses zone scope checks.
    """
    if not has_permission(user, permission):
        return False

    # super_admin has access to all zones
    if user.role == "super_admin":
        return True

    # For roles that only need global permission (approver, etc.)
    if permission in ("approve_requests", "view_audit", "manage_users"):
        return True

    # Check per-zone access
    if not user.zone_access:
        return False

    for access in user.zone_access:
        if access.zone.zone_name == zone_name:
            if permission in (access.permissions or []):
                return True
        # Check pattern matching (e.g., *.cnooc.com.cn)
        if access.zone_pattern:
            if _match_zone_pattern(zone_name, access.zone_pattern):
                if permission in (access.permissions or []):
                    return True

    return False


def get_accessible_zones(user: User) -> List[str]:
    """Get list of zone names accessible to user."""
    if user.role == "super_admin":
        return ["*"]  # All zones

    zones = []
    for access in user.zone_access or []:
        if access.zone:
            zones.append(access.zone.zone_name)
    return zones


def get_user_permissions(user: User, zone_name: Optional[str] = None) -> List[str]:
    """Get all effective permissions for a user, optionally scoped to a zone."""
    role_perms = ROLE_PERMISSIONS.get(user.role, [])

    if zone_name:
        # Filter to permissions actually granted for this zone
        effective = []
        for perm in role_perms:
            if has_permission_for_zone(user, zone_name, perm):
                effective.append(perm)
        return effective

    return role_perms


def _match_zone_pattern(zone_name: str, pattern: str) -> bool:
    """Match zone name against a pattern (supports * wildcard)."""
    import fnmatch
    return fnmatch.fnmatch(zone_name, pattern)
