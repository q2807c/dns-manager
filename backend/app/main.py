"""F5 DNS Zone Management Platform — Main Application."""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models import F5Device
from app.services.ssh_connector import ssh_connector
from app.api.routes import auth, zones, records, audit, users, change_requests, devices

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — load devices into SSH connector on startup."""
    await _load_devices()
    yield


async def _load_devices():
    """Load all active F5 devices from DB into SSH connector registry."""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(F5Device).where(F5Device.is_active == True),
            )
            devices_list = result.scalars().all()
            for device in devices_list:
                config = {
                    "host": device.host,
                    "port": device.port,
                    "user": device.username,
                    "password": device.password,
                    "key_path": device.key_path,
                    "key_passphrase": device.key_passphrase,
                    "named_conf_path": device.named_conf_path,
                    "zone_dir": device.zone_dir,
                }
                ssh_connector.register_device(device.id, config)
            logger.info(f"Loaded {len(devices_list)} F5 device(s) from database")
    except Exception as e:
        logger.warning(f"Could not load devices from DB (may be first run): {e}")


app = FastAPI(
    title="DNS Zone Manager",
    description="F5 BIG-IP DNS Zone Management Platform",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(zones.router)
app.include_router(records.router)
app.include_router(audit.router)
app.include_router(users.router)
app.include_router(change_requests.router)
app.include_router(devices.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    configured_count = len(ssh_connector._devices)
    return {
        "status": "ok",
        "version": "0.2.0",
        "f5_active_host": settings.F5_ACTIVE_HOST,
        "configured_devices": configured_count,
    }
