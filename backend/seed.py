"""Initialize database tables and seed default data for local development.

Run directly:  python seed.py
"""
import asyncio
import sys
import os

# Ensure backend root is on path
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, Base, async_session_factory
from app.models import User, Zone, AuditLog, UserZoneAccess, F5Device  # noqa: F401
from app.core.auth import hash_password
from app.config import settings


async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Database tables created")


async def seed_data():
    """Insert default users, zones, device, and access mappings."""
    async with async_session_factory() as db:
        # ── Default F5 Device (from .env settings) ──
        from sqlalchemy import select
        existing_device = await db.execute(
            select(F5Device).where(F5Device.host == settings.F5_ACTIVE_HOST),
        )
        device = existing_device.scalar_one_or_none()
        if not device:
            device = F5Device(
                group_name="BQJ-01",
                host=settings.F5_ACTIVE_HOST,
                port=settings.F5_SSH_PORT,
                username=settings.F5_SSH_USER,
                password=settings.F5_SSH_PASSWORD,
                key_path=settings.F5_SSH_KEY_PATH,
                key_passphrase=settings.F5_SSH_KEY_PASSPHRASE,
                named_conf_path=settings.F5_NAMED_CONF,
                zone_dir=settings.F5_ZONE_DIR,
                is_active=True,
                description="北京北七家数据中心（自动创建）",
            )
            db.add(device)
            await db.flush()
            print(f"✓ Default F5 device created: {device.group_name} ({device.host})")
        else:
            print(f"✓ Existing F5 device found: {device.group_name} ({device.host})")

        # ── Users ──
        users = {
            "admin": User(
                username="admin",
                password_hash=hash_password("admin123"),
                display_name="Super Admin",
                email="admin@cnooc.com.cn",
                role="super_admin",
            ),
            "ops": User(
                username="ops",
                password_hash=hash_password("ops123456"),
                display_name="DNS Operator",
                email="ops@cnooc.com.cn",
                role="zone_operator",
            ),
            "viewer": User(
                username="viewer",
                password_hash=hash_password("view123456"),
                display_name="Read-Only User",
                email="viewer@cnooc.com.cn",
                role="zone_viewer",
            ),
            "approver": User(
                username="approver",
                password_hash=hash_password("appr123456"),
                display_name="Approval Reviewer",
                email="approver@cnooc.com.cn",
                role="approver",
            ),
        }
        for u in users.values():
            db.add(u)
        await db.flush()

        # ── Zones (mirror real F5 device) ──
        zones = {
            "ppv2.com": Zone(
                zone_name="ppv2.com",
                zone_type="master",
                view_name="external",
                file_name="db.external.ppv2.com.",
                record_count=4,
                last_serial="2026073001",
                last_modified_by=users["admin"].id,
                device_id=device.id,
            ),
            "cq-changan-gm.com": Zone(
                zone_name="cq-changan-gm.com",
                zone_type="master",
                view_name="external",
                file_name="db.external.cq-changan-gm.com.",
                record_count=4,
                last_serial="2026073001",
                last_modified_by=users["admin"].id,
                device_id=device.id,
            ),
        }
        for z in zones.values():
            db.add(z)
        await db.flush()

        # ── User-Zone Access — operators get ppv2.com ──
        db.add(UserZoneAccess(
            user_id=users["ops"].id,
            zone_id=zones["ppv2.com"].id,
            permissions=["zone_view", "record_view", "record_add", "record_modify", "record_delete"],
        ))
        db.add(UserZoneAccess(
            user_id=users["viewer"].id,
            zone_id=zones["ppv2.com"].id,
            permissions=["zone_view", "record_view"],
        ))

        # ── Sample audit log ──
        db.add(AuditLog(
            user_id=users["admin"].id,
            username="admin",
            action="zone_discover",
            zone_name="*",
            status="success",
        ))

        await db.commit()
        print("✓ Seed data inserted")
        print()
        print("  Login accounts:")
        print("    admin    / admin123   (super_admin)")
        print("    ops      / ops123456  (zone_operator)")
        print("    viewer   / view123456 (zone_viewer)")
        print("    approver / appr123456 (approver)")


async def main():
    await init_db()
    await seed_data()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
