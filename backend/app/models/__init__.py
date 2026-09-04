"""SQLAlchemy ORM models."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, UniqueConstraint, JSON,
)
from sqlalchemy.orm import relationship
from app.database import Base


class F5Device(Base):
    """F5 BIG-IP device / sync group configuration."""
    __tablename__ = "f5_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(128), unique=True, nullable=False, index=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=22)
    username = Column(String(64), default="root")
    password = Column(Text, nullable=True)
    key_path = Column(String(512), nullable=True)
    key_passphrase = Column(Text, nullable=True)
    named_conf_path = Column(String(512), default="/var/named/config/named.conf")
    zone_dir = Column(String(512), default="/var/named/config/namedb")
    is_active = Column(Boolean, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    zones = relationship("Zone", back_populates="device")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    display_name = Column(String(128))
    email = Column(String(128))
    role = Column(String(32), nullable=False, default="zone_viewer")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    zone_access = relationship("UserZoneAccess", back_populates="user", cascade="all, delete-orphan")
    change_requests = relationship("ChangeRequest", back_populates="user",
                                   foreign_keys="ChangeRequest.user_id")


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zone_name = Column(String(255), unique=True, nullable=False, index=True)
    zone_type = Column(String(16), nullable=False, default="master")
    view_name = Column(String(64), nullable=False, default="external")
    file_name = Column(String(255))
    named_conf_entry = Column(Text)
    record_count = Column(Integer, default=0)
    last_serial = Column(String(16))
    last_modified = Column(DateTime, default=datetime.now)
    last_modified_by = Column(Integer, ForeignKey("users.id"))
    device_id = Column(Integer, ForeignKey("f5_devices.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    modifiers = relationship("User", foreign_keys=[last_modified_by])
    device = relationship("F5Device", back_populates="zones")
    user_access = relationship("UserZoneAccess", back_populates="zone", cascade="all, delete-orphan")


class UserZoneAccess(Base):
    __tablename__ = "user_zone_access"
    __table_args__ = (
        UniqueConstraint("user_id", "zone_id", name="uq_user_zone"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id", ondelete="CASCADE"), nullable=False)
    zone_pattern = Column(String(255))
    permissions = Column(JSON, default=list)

    user = relationship("User", back_populates="zone_access")
    zone = relationship("Zone", back_populates="user_access")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    username = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False)
    zone_name = Column(String(255))
    target_record = Column(Text)
    before_value = Column(Text)
    after_value = Column(Text)
    ssh_command = Column(Text)
    ssh_output = Column(Text)
    status = Column(String(16), nullable=False, default="success")
    ip_address = Column(String(45))
    timestamp = Column(DateTime, default=datetime.now, index=True)


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(32), nullable=False)
    zone_name = Column(String(255), nullable=False)
    payload = Column(JSON)
    summary = Column(Text)
    status = Column(String(16), default="pending")
    approver_id = Column(Integer, ForeignKey("users.id"))
    submitted_at = Column(DateTime, default=datetime.now)
    reviewed_at = Column(DateTime)
    executed_at = Column(DateTime)
    review_comment = Column(Text)

    user = relationship("User", back_populates="change_requests", foreign_keys=[user_id])
    approver = relationship("User", foreign_keys=[approver_id])


class ZoneBackup(Base):
    __tablename__ = "zone_backups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zone_name = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    serial = Column(String(16))
    backed_up_by = Column(Integer, ForeignKey("users.id"))
    backup_type = Column(String(16), default="pre_change")
    created_at = Column(DateTime, default=datetime.now)
