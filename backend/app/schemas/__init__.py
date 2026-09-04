"""Pydantic schemas for request/response models."""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ── Auth ──
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


# ── Zone Access ──
class ZoneAccessEntry(BaseModel):
    zone_id: Optional[int] = None
    zone_pattern: Optional[str] = None
    permissions: List[str] = ["zone_view", "record_view"]

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str
    is_active: bool
    zone_access: List[ZoneAccessEntry] = []

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str = "zone_viewer"
    zone_access: List[ZoneAccessEntry] = []


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    zone_access: Optional[List[ZoneAccessEntry]] = None


# ── Zone ──
class ZoneResponse(BaseModel):
    id: int
    zone_name: str
    zone_type: str
    view_name: str
    file_name: Optional[str] = None
    record_count: int
    last_serial: Optional[str] = None
    last_modified: Optional[datetime] = None
    device_id: Optional[int] = None
    is_active: bool

    class Config:
        from_attributes = True


class ZoneListResponse(BaseModel):
    items: List[ZoneResponse]
    total: int
    page: int
    page_size: int


class ZoneCreateRequest(BaseModel):
    zone_name: str = Field(description="Zone name, e.g. 'example.com'")
    zone_type: str = Field(default="master")
    view_name: str = Field(default="external")
    ttl: int = Field(default=300, ge=0, le=86400)
    master_server: str = Field(default="dns1.cnooc.com.")
    email_contact: str = Field(default="hostmaster.cnooc.com.")
    ns_servers: List[str] = Field(default_factory=list)
    create_a_record: bool = Field(default=False)
    a_record_ip: Optional[str] = None
    device_id: Optional[int] = Field(default=None, description="目标 F5 设备 ID")


# ── DNS Record ──
class DNSRecord(BaseModel):
    name: str
    type: str
    ttl: int
    data: str


class DNSRecordCreate(BaseModel):
    name: str = Field(default="@", description="Record name (hostname portion)")
    type: str = Field(description="Record type: A, AAAA, CNAME, MX, NS, SRV, TXT, PTR")
    ttl: int = Field(default=300, ge=0, le=86400)
    data: str = Field(description="Record data, format depends on type")
    priority: Optional[int] = Field(default=None, description="Priority for MX, SRV")
    weight: Optional[int] = Field(default=None, description="Weight for SRV")
    port: Optional[int] = Field(default=None, description="Port for SRV")


class DNSRecordUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    ttl: Optional[int] = None
    data: Optional[str] = None
    priority: Optional[int] = None
    weight: Optional[int] = None
    port: Optional[int] = None


class DNSRecordResponse(BaseModel):
    id: int
    name: str
    type: str
    ttl: int
    data: str

    class Config:
        from_attributes = True


class RecordListResponse(BaseModel):
    items: List[DNSRecordResponse]
    total: int
    page: int
    page_size: int
    zone_name: str
    zone_serial: Optional[str] = None


# ── Raw Zone ──
class RawZoneResponse(BaseModel):
    zone_name: str
    content: str
    serial: Optional[str] = None


class RawZoneUpdate(BaseModel):
    content: str


# ── Audit ──
class AuditLogResponse(BaseModel):
    id: int
    username: str
    action: str
    zone_name: Optional[str] = None
    target_record: Optional[str] = None
    before_value: Optional[str] = None
    after_value: Optional[str] = None
    status: str
    ip_address: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class AuditListResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int


# ── Change Request ──
class ChangeRequestCreate(BaseModel):
    action: str = Field(description="record_create | record_modify | record_delete | zone_create | zone_delete | raw_zone_edit")
    zone_name: str
    payload: dict = Field(default_factory=dict)
    summary: Optional[str] = Field(default=None, description="Human-readable summary of the change")


class ChangeRequestReview(BaseModel):
    action: str = Field(description="approve | reject")
    comment: Optional[str] = None


class ChangeRequestResponse(BaseModel):
    id: int
    submitted_by: str = ""
    action: str
    zone_name: str
    payload: Optional[dict] = None
    status: str
    summary: Optional[str] = None
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    reviewer: Optional[str] = None

    class Config:
        from_attributes = True


class ChangeRequestListResponse(BaseModel):
    items: List[ChangeRequestResponse]
    total: int
    page: int
    page_size: int


# ── Backup ──
class ZoneBackupResponse(BaseModel):
    id: int
    zone_name: str
    serial: Optional[str] = None
    backup_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class ZoneBackupDetailResponse(ZoneBackupResponse):
    content: str


# ── F5 Device ──
class F5DeviceCreate(BaseModel):
    group_name: str = Field(min_length=1, max_length=128, description="同步组名称（唯一）")
    host: str = Field(min_length=1, max_length=255, description="F5 设备地址")
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(default="root", max_length=64)
    password: Optional[str] = Field(default=None, description="SSH 密码（留空使用密钥认证）")
    key_path: Optional[str] = Field(default=None, max_length=512, description="SSH 私钥路径")
    key_passphrase: Optional[str] = Field(default=None, description="私钥密码短语")
    named_conf_path: str = Field(default="/var/named/config/named.conf", max_length=512)
    zone_dir: str = Field(default="/var/named/config/namedb", max_length=512)
    is_active: bool = Field(default=True)
    description: Optional[str] = None


class F5DeviceUpdate(BaseModel):
    group_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    host: Optional[str] = Field(default=None, min_length=1, max_length=255)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = Field(default=None, max_length=64)
    password: Optional[str] = None
    key_path: Optional[str] = Field(default=None, max_length=512)
    key_passphrase: Optional[str] = None
    named_conf_path: Optional[str] = Field(default=None, max_length=512)
    zone_dir: Optional[str] = Field(default=None, max_length=512)
    is_active: Optional[bool] = None
    description: Optional[str] = None


class F5DeviceResponse(BaseModel):
    id: int
    group_name: str
    host: str
    port: int
    username: str
    # password and key_passphrase are NOT returned in responses
    key_path: Optional[str] = None
    named_conf_path: str
    zone_dir: str
    is_active: bool
    description: Optional[str] = None
    zone_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class F5DeviceListResponse(BaseModel):
    items: List[F5DeviceResponse]
    total: int


# ── Zone Sync ──
class ZoneSyncItem(BaseModel):
    zone_name: str
    device_group: str
    status: str  # "created", "exists", "error"
    detail: Optional[str] = None


class ZoneSyncResponse(BaseModel):
    synced: int = 0
    updated: int = 0
    already_exists: int = 0
    errors: int = 0
    total: int = 0
    items: List[ZoneSyncItem] = []
