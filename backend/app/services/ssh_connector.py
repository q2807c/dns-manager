"""SSH connector for F5 BIG-IP DNS operations.

Key facts (verified against F5 BIG-IP VE 17.1.2.1 / BIND 9.16.33):
- named runs in chroot: -t /var/named
- named.conf: /config/named.conf (chroot) = /var/named/config/named.conf (real FS)
- Zone dir: /config/namedb/ (chroot) = /var/named/config/namedb/ (real FS)
- Zone file naming: db.external.{zone_name}. (trailing dot)
- rndc auto-detects key (no -k needed)
- Zone editing workflow: rndc sync -clean <zone> → edit file → rndc reload <zone>
  (sync -clean flushes .jnl journal to zone file before editing)

Multi-device support:
- Each F5 device/sync-group is identified by an integer device_id.
- Device configs are registered via register_device().
- All SSH methods accept an optional device_id — if None, the first
  registered active device is used, falling back to settings.
"""
import asyncio
import concurrent.futures
import functools
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import paramiko
from app.config import settings
from app.services.zone_parser import (
    extract_records,
    parse_zone_text,
    validate_zone_syntax,
)

logger = logging.getLogger(__name__)


# ── Non-blocking execution helper ──────────────────────────────────
#
# paramiko is fully blocking: a connect timeout can stall for up to
# ~45s (connect 15s + banner 15s + auth 15s). Calling it directly from
# async routes blocks the asyncio event loop and freezes EVERY endpoint
# (observed: a device "test connection" stalled GET /api/users for 14s).
#
# A dedicated single-worker thread executor:
#   * keeps the event loop free, and
#   * serializes SSH work, which also protects the shared
#     SSHClient cache in SSHConnector from concurrent access.

_ssh_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="ssh-worker",
)


async def run_ssh(fn, *args, **kwargs):
    """Run a blocking ssh_connector call in the SSH worker thread.

    Usage (inside async route handlers / helpers):
        exit_code, out, err = await run_ssh(
            ssh_connector.exec_command, "hostname", device_id=1)
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _ssh_executor, functools.partial(fn, **kwargs), *args,
    )


# ── named.conf zone-stanza surgery ─────────────────────────────────
#
# named.conf is edited as text, and the obvious regex for removing a stanza
#
#     r'\n\s*zone\s+"name\."\s*\{[^}]*\};'
#
# is wrong: `[^}]*` stops at the FIRST '}', which is the closing brace of the
# nested `allow-update { ... };` block, so the zone's own trailing '};' is left
# behind as an orphan. One orphaned brace is enough to make named.conf
# syntactically invalid (`named-checkconf: syntax error near '}'`) — and because
# named keeps answering from its in-memory copy, nothing looks broken until the
# next reload or restart, long after the file was written. This happened in
# production: deleting a zone silently corrupted the device's named.conf.
#
# These helpers walk braces instead of trusting a regex, and every writer below
# validates the result (named-checkconf) and rolls back on failure.


def find_zone_stanza(text: str, zone_name: str) -> Optional[Tuple[int, int]]:
    """Return the (start, end) span of the `zone "<name>." { ... };` stanza.

    Brace-aware: walks to the brace that actually closes the stanza, so nested
    blocks (`allow-update { ... };`) do not cut the match short. Returns None
    when the stanza is absent or the braces are unbalanced.
    """
    match = re.search(
        rf'^[ \t]*zone\s+"{re.escape(zone_name)}\."\s*\{{', text, re.MULTILINE,
    )
    if not match:
        return None
    open_brace = match.end() - 1  # the pattern ends on the '{'
    depth = 0
    for i in range(open_brace, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                semicolon = text.find(";", i)
                if semicolon == -1:
                    return None
                end = semicolon + 1
                while end < len(text) and text[end] in " \t":
                    end += 1
                if end < len(text) and text[end] == "\n":
                    end += 1
                start = match.start()
                # Swallow the single blank line that insert_zone_stanza() puts
                # before a stanza, so create → delete round-trips byte-for-byte
                # instead of accumulating blank lines pass after pass.
                if start > 0 and text[start - 1] == "\n":
                    prev_line_end = start - 1
                    prev_line_start = text.rfind("\n", 0, prev_line_end) + 1
                    if not text[prev_line_start:prev_line_end].strip():
                        start = prev_line_start
                return start, end
    return None  # unbalanced — never guess


def remove_zone_stanza(text: str, zone_name: str) -> str:
    """Remove a zone stanza from named.conf. Returns *text* unchanged if absent."""
    span = find_zone_stanza(text, zone_name)
    if span is None:
        return text
    return text[:span[0]] + text[span[1]:]


def insert_zone_stanza(text: str, stanza: str) -> str:
    """Insert *stanza* as the last entry of `view "external"`."""
    stripped = text.rstrip()
    if not stripped.endswith("};"):
        raise RuntimeError(
            "named.conf does not end with the view's closing '};' — refusing to edit",
        )
    # F5 writes named.conf without a trailing newline; keep whatever the file
    # had so create → delete restores it byte-for-byte.
    tail = "\n" if text.endswith("\n") else ""
    return stripped[:-2].rstrip("\n") + "\n" + stanza + "};" + tail


def named_conf_braces_balanced(text: str) -> bool:
    """Structural sanity check for named.conf (used by the file-backed connector)."""
    depth = 0
    for char in text:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


# ── Default config (from settings) ─────────────────────────────────

def _default_device_config() -> Dict[str, Any]:
    """Build device config dict from app settings (fallback)."""
    return {
        "host": settings.F5_ACTIVE_HOST,
        "port": settings.F5_SSH_PORT,
        "user": settings.F5_SSH_USER,
        "password": settings.F5_SSH_PASSWORD,
        "key_path": settings.F5_SSH_KEY_PATH,
        "key_passphrase": settings.F5_SSH_KEY_PASSPHRASE,
        "named_conf_path": settings.F5_NAMED_CONF,
        "zone_dir": settings.F5_ZONE_DIR,
    }


class SSHConnector:
    """Manages SSH connections to multiple F5 BIG-IP nodes."""

    def __init__(self):
        # device_id → config dict
        self._devices: Dict[int, Dict[str, Any]] = {}
        # device_id → paramiko SSHClient
        self._clients: Dict[int, paramiko.SSHClient] = {}

    # ── Device registry ─────────────────────────────────────────────

    def register_device(self, device_id: int, config: Dict[str, Any]):
        """Register or update a device configuration."""
        self._devices[device_id] = config
        logger.info(f"Device {device_id} ({config.get('host')}) registered")

    def is_registered(self, device_id: int) -> bool:
        """Whether this device is currently registered (i.e. loaded from DB
        at startup or via register_device) — callers must not unregister a
        device they did not register themselves."""
        return device_id in self._devices

    def unregister_device(self, device_id: int):
        """Remove a device and close its connection."""
        self._devices.pop(device_id, None)
        client = self._clients.pop(device_id, None)
        if client:
            try:
                client.close()
            except Exception:
                pass
        logger.info(f"Device {device_id} unregistered")

    def get_device_config(self, device_id: Optional[int] = None) -> Dict[str, Any]:
        """Resolve device config by id, or first active device, or fallback."""
        if device_id is not None and device_id in self._devices:
            return self._devices[device_id]
        if self._devices:
            return next(iter(self._devices.values()))
        return _default_device_config()

    # ── Connection management ──────────────────────────────────────

    def _ensure_connected(self, device_id: Optional[int] = None):
        """Ensure SSH connection is active for the given device."""
        cfg = self.get_device_config(device_id)
        actual_id = self._resolve_device_id(device_id)

        client = self._clients.get(actual_id)
        if client and client.get_transport() and client.get_transport().is_active():
            return

        self._connect(actual_id, cfg)

    def _resolve_device_id(self, device_id: Optional[int] = None) -> int:
        """Map device_id to a usable integer key (for connection cache)."""
        if device_id is not None and device_id in self._devices:
            return device_id
        if self._devices:
            return next(iter(self._devices))
        return 0  # fallback key for settings-based device

    def _connect(self, device_id: int, cfg: Dict[str, Any]):
        """Establish SSH connection to a device."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        pkey = None
        key_path = cfg.get("key_path")
        key_passphrase = cfg.get("key_passphrase")
        if key_path:
            try:
                pkey = paramiko.Ed25519Key.from_private_key_file(
                    key_path, password=key_passphrase or None,
                )
            except (paramiko.SSHException, FileNotFoundError):
                try:
                    pkey = paramiko.RSAKey.from_private_key_file(
                        key_path, password=key_passphrase or None,
                    )
                except (paramiko.SSHException, FileNotFoundError):
                    pkey = None

        connect_kwargs = {
            "hostname": cfg["host"],
            "port": cfg.get("port", 22),
            "username": cfg.get("user", "root"),
            "timeout": 15,
            "banner_timeout": 15,
            "auth_timeout": 15,
        }

        if pkey:
            connect_kwargs["pkey"] = pkey
        elif cfg.get("password"):
            connect_kwargs["password"] = cfg["password"]

        client.connect(**connect_kwargs)
        self._clients[device_id] = client
        logger.info(f"SSH connected to {cfg['host']}:{cfg.get('port', 22)} (device {device_id})")

    def close(self, device_id: Optional[int] = None):
        """Close SSH connection(s). If device_id is None, close all."""
        if device_id is not None:
            client = self._clients.pop(device_id, None)
            if client:
                client.close()
        else:
            for cid, client in list(self._clients.items()):
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()

    # ── Command execution ──────────────────────────────────────────

    def exec_command(
        self, command: str, timeout: int = 30, device_id: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        """Execute a command over SSH.

        Returns (exit_code, stdout, stderr).
        """
        self._ensure_connected(device_id)
        actual_id = self._resolve_device_id(device_id)
        client = self._clients[actual_id]
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return (
            exit_code,
            stdout.read().decode("utf-8", errors="replace"),
            stderr.read().decode("utf-8", errors="replace"),
        )

    # ── File I/O (SFTP) ────────────────────────────────────────────

    def read_file(self, remote_path: str, device_id: Optional[int] = None) -> str:
        """Read a file over SFTP."""
        self._ensure_connected(device_id)
        actual_id = self._resolve_device_id(device_id)
        client = self._clients[actual_id]
        sftp = client.open_sftp()
        try:
            with sftp.file(remote_path, "r") as f:
                return f.read().decode("utf-8", errors="replace")
        finally:
            sftp.close()

    def write_file(self, remote_path: str, content: str, device_id: Optional[int] = None):
        """Write content to a file over SFTP."""
        self._ensure_connected(device_id)
        actual_id = self._resolve_device_id(device_id)
        client = self._clients[actual_id]
        sftp = client.open_sftp()
        try:
            with sftp.file(remote_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()

    def list_dir(self, remote_path: str, device_id: Optional[int] = None) -> List[str]:
        """List filenames in a remote directory via SFTP."""
        self._ensure_connected(device_id)
        actual_id = self._resolve_device_id(device_id)
        client = self._clients[actual_id]
        sftp = client.open_sftp()
        try:
            return sftp.listdir(remote_path)
        finally:
            sftp.close()

    # ── Per-device path helpers ────────────────────────────────────

    def _zone_dir(self, device_id: Optional[int] = None) -> str:
        return self.get_device_config(device_id).get(
            "zone_dir", settings.F5_ZONE_DIR,
        )

    def _named_conf_path(self, device_id: Optional[int] = None) -> str:
        return self.get_device_config(device_id).get(
            "named_conf_path", settings.F5_NAMED_CONF,
        )

    def _zone_file_path(self, zone_name: str, device_id: Optional[int] = None) -> str:
        """Get the absolute real-FS path to a zone file.

        Naming convention: db.external.{zone_name}. (trailing dot).
        """
        return f"{self._zone_dir(device_id)}/db.external.{zone_name}."

    # ── Zone discovery ─────────────────────────────────────────────

    def discover_zones(self, device_id: Optional[int] = None) -> List[str]:
        """Discover zone names from named.conf on the F5 device."""
        content = self.read_file(self._named_conf_path(device_id), device_id=device_id)
        zones = re.findall(r'zone\s+"([^"]+)"\s*\{', content)
        return [z.rstrip(".") for z in zones]

    def list_zone_files(self, device_id: Optional[int] = None) -> List[str]:
        """List physical zone files in the zone directory."""
        all_files = self.list_dir(self._zone_dir(device_id), device_id=device_id)
        return sorted(
            f for f in all_files
            if f.startswith("db.external.")
            and not f.endswith(".jnl")
            and not f.endswith(".bak")
            and ".bak." not in f
        )

    # ── Zone editing workflow ──────────────────────────────────────

    def sync_zone(self, zone_name: str, device_id: Optional[int] = None) -> Tuple[int, str, str]:
        """Flush .jnl journal to zone file and remove journal."""
        return self.exec_command(f"rndc sync -clean {zone_name}", device_id=device_id)

    def reload_zone(self, zone_name: str, device_id: Optional[int] = None) -> Tuple[int, str, str]:
        """Reload a specific zone via rndc."""
        return self.exec_command(f"rndc reload {zone_name}", device_id=device_id)

    def reconfig_named(self, device_id: Optional[int] = None) -> Tuple[int, str, str]:
        """Reload named.conf via rndc reconfig."""
        exit_code, stdout, stderr = self.exec_command("rndc reconfig", device_id=device_id)
        if exit_code != 0:
            raise RuntimeError(f"rndc reconfig failed (exit={exit_code}): {stderr}")
        return exit_code, stdout, stderr

    # ── Zone editing (full workflow) ───────────────────────────────

    def begin_zone_edit(
        self, zone_name: str, device_id: Optional[int] = None,
    ) -> Tuple[str, str]:
        """Prepare a zone for editing: sync journal, backup, return content.

        Returns (zone_content, backup_file_path).
        """
        exit_code, out, err = self.sync_zone(zone_name, device_id=device_id)
        if exit_code != 0:
            raise RuntimeError(f"rndc sync -clean failed: {err}")

        backup_file = self.backup_zone_file(zone_name, device_id=device_id)
        zone_file = self._zone_file_path(zone_name, device_id)
        content = self.read_file(zone_file, device_id=device_id)

        logger.info(f"Zone edit started for {zone_name}, backup: {backup_file}")
        return content, backup_file

    def end_zone_edit(
        self, zone_name: str, new_content: str, device_id: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        """Write new zone content and reload."""
        zone_file = self._zone_file_path(zone_name, device_id)
        self.write_file(zone_file, new_content, device_id=device_id)
        return self.reload_zone(zone_name, device_id=device_id)

    def rollback_zone_edit(
        self, zone_name: str, backup_file: str, device_id: Optional[int] = None,
    ):
        """Restore zone file from backup and reload."""
        zone_file = self._zone_file_path(zone_name, device_id)
        self.exec_command(f"cp {backup_file} {zone_file}", device_id=device_id)
        self.sync_zone(zone_name, device_id=device_id)
        self.reload_zone(zone_name, device_id=device_id)
        self.exec_command(f"rm -f {backup_file}", device_id=device_id)
        logger.info(f"Zone {zone_name} rolled back from {backup_file}")

    # ── Zone CRUD operations ───────────────────────────────────────

    def read_zone(self, zone_name: str, device_id: Optional[int] = None) -> str:
        """Read the current zone file content."""
        return self.read_file(
            self._zone_file_path(zone_name, device_id), device_id=device_id,
        )

    def backup_zone_file(
        self, zone_name: str, device_id: Optional[int] = None,
    ) -> str:
        """Create/overwrite a single backup of a zone file on the F5 device.

        Uses a fixed filename (no timestamp) — each new backup overwrites the previous one.
        """
        zone_file = self._zone_file_path(zone_name, device_id)
        backup_file = f"{zone_file}.bak"
        self.exec_command(f"cp {zone_file} {backup_file}", device_id=device_id)
        return backup_file

    def backup_named_conf(self, device_id: Optional[int] = None) -> str:
        """Create/overwrite a single backup of named.conf on the F5 device."""
        named_conf = self._named_conf_path(device_id)
        backup_file = f"{named_conf}.bak"
        self.exec_command(f"cp {named_conf} {backup_file}", device_id=device_id)
        return backup_file

    def create_zone(self, zone_name: str, content: str, device_id: Optional[int] = None):
        """Create a new zone file and add it to named.conf."""
        import time

        named_conf_path = self._named_conf_path(device_id)
        zone_file = self._zone_file_path(zone_name, device_id)
        self.write_file(zone_file, content, device_id=device_id)

        # Validate zone syntax before touching named.conf
        ok, msg = self.named_checkzone(zone_name, device_id=device_id)
        if not ok:
            self.exec_command(f"rm -f {zone_file}", device_id=device_id)
            raise RuntimeError(f"Zone syntax check failed for {zone_name}: {msg}")

        # Add zone stanza to named.conf
        backup_file = self.backup_named_conf(device_id=device_id)
        named_conf = self.read_file(named_conf_path, device_id=device_id)
        if 'view "external"' not in named_conf:
            self.exec_command(f"rm -f {zone_file}", device_id=device_id)
            raise RuntimeError('named.conf 中找不到 view "external"，已中止（未改动设备）')
        stanza = (
            f'\n    zone "{zone_name}." {{\n'
            f'        type master;\n'
            f'        file "db.external.{zone_name}.";\n'
            f'        allow-update {{\n'
            f'            localhost;\n'
            f'        }};\n'
            f'    }};\n'
        )
        try:
            self._write_named_conf_checked(
                insert_zone_stanza(named_conf, stanza), backup_file,
                device_id=device_id,
            )
        except Exception:
            # named.conf was rolled back — do not leave the new zone file behind
            self.exec_command(f"rm -f {zone_file}", device_id=device_id)
            raise

        self.reconfig_named(device_id=device_id)

        for i in range(5):
            time.sleep(0.5)
            result = self.dig_query(f"{zone_name} SOA", device_id=device_id)
            if result:
                return
        raise RuntimeError(f"Zone {zone_name} created but SOA not resolving after reload")

    def delete_zone(self, zone_name: str, device_id: Optional[int] = None):
        """Delete a zone file and remove its stanza from named.conf."""
        named_conf_path = self._named_conf_path(device_id)
        zone_file = self._zone_file_path(zone_name, device_id)

        backup_file = self.backup_named_conf(device_id=device_id)
        named_conf = self.read_file(named_conf_path, device_id=device_id)
        updated = remove_zone_stanza(named_conf, zone_name)

        if updated == named_conf:
            # Previously this fell through to a silent no-op + reload, which hid
            # the fact that nothing was deleted (and masked a half-applied edit).
            logger.warning(
                'delete_zone(%s): named.conf has no matching zone stanza; '
                'removing the zone file only', zone_name,
            )
        else:
            self._write_named_conf_checked(updated, backup_file, device_id=device_id)
            self.reconfig_named(device_id=device_id)

        self.exec_command(f"rm -f {zone_file}", device_id=device_id)
        self.exec_command(f"rm -f {zone_file}.jnl", device_id=device_id)

    # ── Validation ─────────────────────────────────────────────────

    def dig_query(self, query: str, device_id: Optional[int] = None) -> str:
        """Execute a dig query on the F5 node."""
        _, stdout, _ = self.exec_command(
            f"dig @127.0.0.1 {query} +short", device_id=device_id,
        )
        return stdout.strip()

    def named_checkzone(
        self, zone_name: str, device_id: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Run named-checkzone on the F5 device to validate syntax.

        Returns (is_valid, message).
        """
        zone_file = self._zone_file_path(zone_name, device_id)
        exit_code, stdout, stderr = self.exec_command(
            f"named-checkzone {zone_name} {zone_file}", device_id=device_id,
        )
        return exit_code == 0, stdout + "\n" + stderr

    def named_checkconf(self, device_id: Optional[int] = None) -> Tuple[bool, str]:
        """Validate named.conf on the device with named-checkconf.

        BIG-IP runs named chrooted under /var/named, so the check needs -t plus
        a chroot-relative path; without -t, checkconf cannot resolve
        `directory "/config/namedb"` and reports a false failure.

        Returns (is_valid, message).
        """
        named_conf = self._named_conf_path(device_id)
        target = named_conf
        if named_conf.startswith("/var/named/"):
            target = f"-t /var/named {named_conf[len('/var/named'):]}"
        exit_code, stdout, stderr = self.exec_command(
            f"/usr/sbin/named-checkconf {target} 2>&1", device_id=device_id,
        )
        return exit_code == 0, (stdout + stderr).strip()

    def _write_named_conf_checked(
        self, new_content: str, backup_file: str, device_id: Optional[int] = None,
    ):
        """Write named.conf, validate it, and roll back if it is broken.

        Nothing else notices a corrupt named.conf: named keeps serving from its
        in-memory copy, so the damage stays invisible until the next reload or
        restart — exactly how a bad edit once survived unnoticed on a live
        device. Refusing to leave an unloadable file behind is the only safe
        behaviour.
        """
        named_conf_path = self._named_conf_path(device_id)
        self.write_file(named_conf_path, new_content, device_id=device_id)
        ok, message = self.named_checkconf(device_id=device_id)
        if not ok:
            self.exec_command(
                f"cp {backup_file} {named_conf_path}", device_id=device_id,
            )
            logger.error("named.conf validation failed, rolled back: %s", message)
            raise RuntimeError(
                f"named.conf 校验失败，已回滚（未对设备生效）: {message}",
            )


# ── Offline demo mode ──────────────────────────────────────────────
#
# DEMO_MODE=true swaps the SSH-backed connector for this file-backed one:
# the platform stays fully browsable and editable (zones, records, change
# requests, backups, reloads) without any BIG-IP on site — which is what a
# demo / POC instance needs when the real F5 is only reachable from
# somewhere else.
#
# Everything is served from DEMO_DATA_DIR, mirroring the F5 layout:
#
#     DEMO_DATA_DIR/
#         named.conf                    # zone list, same syntax as F5
#         namedb/db.external.<zone>.    # zone files, same naming as F5
#
# To present real data, point DEMO_DATA_DIR at a copy of an exported F5
# config (see docs/DEMO_MODE.md). Devices in the DB are ignored — the
# "connection" always succeeds, so the device page keeps working.


class DemoConnector:
    """File-backed stand-in for :class:`SSHConnector` (DEMO_MODE only)."""

    DEMO_HOSTNAME = "bigip-demo.f5.com"

    def __init__(self):
        self.root = Path(settings.DEMO_DATA_DIR).expanduser().resolve()
        self.named_conf = self.root / "named.conf"
        self.zone_dir = self.root / "namedb"
        self.zone_dir.mkdir(parents=True, exist_ok=True)
        self._devices: Dict[int, Dict[str, Any]] = {}
        if not self.named_conf.exists():
            self.named_conf.write_text('view "external" {\n};\n')
        logger.warning(
            "DEMO MODE is ON — all F5 operations are simulated from %s", self.root,
        )

    # ── Device registry (no SSH session is ever opened) ────────────

    def register_device(self, device_id: int, config: Dict[str, Any]):
        self._devices[device_id] = dict(config or {})
        logger.info(f"Device {device_id} registered (demo mode)")

    def is_registered(self, device_id: int) -> bool:
        return device_id in self._devices

    def unregister_device(self, device_id: int):
        self._devices.pop(device_id, None)

    def get_device_config(self, device_id: Optional[int] = None) -> Dict[str, Any]:
        if device_id is not None and device_id in self._devices:
            return self._devices[device_id]
        if self._devices:
            return next(iter(self._devices.values()))
        return {"host": self.DEMO_HOSTNAME, "port": 22, "user": "root"}

    def close(self, device_id: Optional[int] = None):
        self._clients = {}

    # ── Path mapping ───────────────────────────────────────────────

    def _zone_dir(self, device_id: Optional[int] = None) -> str:
        return str(self.zone_dir)

    def _named_conf_path(self, device_id: Optional[int] = None) -> str:
        return str(self.named_conf)

    def _zone_file_path(self, zone_name: str, device_id: Optional[int] = None) -> str:
        return str(self.zone_dir / f"db.external.{zone_name}.")

    def _local_path(self, remote_path: str) -> Path:
        """Map any F5 path onto its counterpart inside DEMO_DATA_DIR."""
        name = Path(str(remote_path)).name
        if name.startswith("named.conf"):
            return self.root / name
        return self.zone_dir / name

    # ── File I/O ───────────────────────────────────────────────────

    def read_file(self, remote_path: str, device_id: Optional[int] = None) -> str:
        path = self._local_path(remote_path)
        if not path.exists():
            raise FileNotFoundError(f"[demo] no such file: {path.name}")
        return path.read_text()

    def write_file(self, remote_path: str, content: str, device_id: Optional[int] = None):
        path = self._local_path(remote_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def list_dir(self, remote_path: str, device_id: Optional[int] = None) -> List[str]:
        return [p.name for p in self.zone_dir.iterdir()]

    # ── Command execution (simulated) ──────────────────────────────

    def exec_command(
        self, command: str, timeout: int = 30, device_id: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        cmd = command.strip()

        if cmd.startswith("cp "):
            parts = cmd.split()
            if len(parts) >= 3:
                shutil.copy2(self._local_path(parts[-2]), self._local_path(parts[-1]))
            return 0, "", ""
        if cmd.startswith("rm "):
            for token in cmd.split()[1:]:
                if not token.startswith("-"):
                    self._local_path(token).unlink(missing_ok=True)
            return 0, "", ""
        if cmd.startswith("dig"):
            return 0, self._dig(cmd), ""
        if cmd.startswith("rndc"):
            return 0, "zone reload up-to-date\n", ""
        if cmd.startswith("named-checkzone"):
            return 0, "zone loaded: ok\n", ""
        if "hostname" in cmd or "uname -n" in cmd:
            return 0, f"OK\n{self.DEMO_HOSTNAME}\n", ""
        return 0, "", ""

    # ── Zone discovery / reading ───────────────────────────────────

    def _iter_zones(self):
        """Yield (zone_name, content) for every real zone file."""
        for path in sorted(self.zone_dir.iterdir()):
            name = path.name
            if (
                not name.startswith("db.external.")
                or name.endswith(".jnl")
                or name.endswith(".bak")
                or ".bak." in name
            ):
                continue
            try:
                yield name[len("db.external."):].rstrip("."), path.read_text()
            except OSError:
                continue

    def discover_zones(self, device_id: Optional[int] = None) -> List[str]:
        content = self.read_file(self._named_conf_path(device_id), device_id=device_id)
        zones = re.findall(r'zone\s+"([^"]+)"\s*\{', content)
        return [z.rstrip(".") for z in zones]

    def list_zone_files(self, device_id: Optional[int] = None) -> List[str]:
        return sorted(
            p.name for p in self.zone_dir.iterdir()
            if p.name.startswith("db.external.")
            and not p.name.endswith(".jnl")
            and not p.name.endswith(".bak")
            and ".bak." not in p.name
        )

    def read_zone(self, zone_name: str, device_id: Optional[int] = None) -> str:
        return self.read_file(self._zone_file_path(zone_name, device_id), device_id=device_id)

    def sync_zone(self, zone_name: str, device_id: Optional[int] = None) -> Tuple[int, str, str]:
        return 0, f"zone {zone_name} synced\n", ""

    def reload_zone(self, zone_name: str, device_id: Optional[int] = None) -> Tuple[int, str, str]:
        return 0, "zone reload up-to-date\n", ""

    def reconfig_named(self, device_id: Optional[int] = None) -> Tuple[int, str, str]:
        return 0, "reconfig done\n", ""

    def dig_query(self, query: str, device_id: Optional[int] = None) -> str:
        return self._dig(f"dig @127.0.0.1 {query} +short")

    def _dig(self, cmd: str) -> str:
        """Answer `<name> <type>` queries from the local zone files."""
        tokens = [t for t in cmd.split() if not t.startswith("@") and not t.startswith("+")]
        if len(tokens) < 3:
            return ""
        name, rtype = tokens[-2].rstrip("."), tokens[-1].upper()
        for zone_name, content in self._iter_zones():
            if not (name == zone_name or name.endswith("." + zone_name)):
                continue
            try:
                zone = parse_zone_text(content, zone_name)
                for record in extract_records(zone, zone_name):
                    if record.type.upper() == rtype:
                        return record.data + "\n"
            except Exception:
                continue
        return ""

    # ── Backup / edit workflows ────────────────────────────────────

    def backup_zone_file(self, zone_name: str, device_id: Optional[int] = None) -> str:
        zone_file = self._zone_file_path(zone_name, device_id)
        backup_file = f"{zone_file}.bak"
        self.exec_command(f"cp {zone_file} {backup_file}")
        return backup_file

    def backup_named_conf(self, device_id: Optional[int] = None) -> str:
        backup_file = f"{self.named_conf}.bak"
        shutil.copy2(self.named_conf, backup_file)
        return backup_file

    def begin_zone_edit(
        self, zone_name: str, device_id: Optional[int] = None,
    ) -> Tuple[str, str]:
        self.sync_zone(zone_name, device_id=device_id)
        backup_file = self.backup_zone_file(zone_name, device_id=device_id)
        return self.read_zone(zone_name, device_id=device_id), backup_file

    def end_zone_edit(
        self, zone_name: str, new_content: str, device_id: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        self.write_file(self._zone_file_path(zone_name, device_id), new_content, device_id=device_id)
        return self.reload_zone(zone_name, device_id=device_id)

    def rollback_zone_edit(
        self, zone_name: str, backup_file: str, device_id: Optional[int] = None,
    ):
        self.exec_command(f"cp {backup_file} {self._zone_file_path(zone_name, device_id)}")
        self.sync_zone(zone_name, device_id=device_id)
        self.reload_zone(zone_name, device_id=device_id)
        self.exec_command(f"rm -f {backup_file}")

    # ── Validation ─────────────────────────────────────────────────

    def named_checkzone(
        self, zone_name: str, device_id: Optional[int] = None,
    ) -> Tuple[bool, str]:
        try:
            content = self.read_zone(zone_name, device_id=device_id)
        except FileNotFoundError:
            return False, f"[demo] zone file not found for {zone_name}"
        ok, errors = validate_zone_syntax(content)
        return ok, "zone loaded: ok" if ok else "; ".join(errors)

    def named_checkconf(self, device_id: Optional[int] = None) -> Tuple[bool, str]:
        """Structural check of the local named.conf copy (demo stand-in for
        named-checkconf). Mirrors the device-side guard so the demo instance
        cannot drift into a state the real one would reject."""
        try:
            text = self.named_conf.read_text()
        except FileNotFoundError:
            return False, "[demo] named.conf not found"
        if named_conf_braces_balanced(text):
            return True, ""
        return False, "[demo] named.conf 花括号不平衡"

    def _write_named_conf_checked(
        self, new_content: str, backup_file: str, device_id: Optional[int] = None,
    ):
        self.named_conf.write_text(new_content)
        ok, message = self.named_checkconf(device_id=device_id)
        if not ok:
            shutil.copy2(backup_file, self.named_conf)
            logger.error("named.conf validation failed, rolled back: %s", message)
            raise RuntimeError(
                f"named.conf 校验失败，已回滚（未生效）: {message}",
            )

    # ── Zone CRUD ──────────────────────────────────────────────────

    def create_zone(self, zone_name: str, content: str, device_id: Optional[int] = None):
        zone_file = self._zone_file_path(zone_name, device_id)
        self.write_file(zone_file, content, device_id=device_id)

        ok, message = self.named_checkzone(zone_name, device_id=device_id)
        if not ok:
            self._local_path(zone_file).unlink(missing_ok=True)
            raise RuntimeError(f"Zone syntax check failed for {zone_name}: {message}")

        self.backup_named_conf(device_id=device_id)
        named_conf = self.read_file(self._named_conf_path(device_id), device_id=device_id)
        stanza = (
            f'\n    zone "{zone_name}." {{\n'
            f'        type master;\n'
            f'        file "db.external.{zone_name}.";\n'
            f'        allow-update {{\n'
            f'            localhost;\n'
            f'        }};\n'
            f'    }};\n'
        )
        if 'view "external"' not in named_conf:
            self._local_path(zone_file).unlink(missing_ok=True)
            raise RuntimeError('named.conf 中找不到 view "external"，已中止（未改动）')
        try:
            self._write_named_conf_checked(
                insert_zone_stanza(named_conf, stanza),
                f"{self.named_conf}.bak", device_id=device_id,
            )
        except Exception:
            self._local_path(zone_file).unlink(missing_ok=True)
            raise

        if not self.dig_query(f"{zone_name} SOA", device_id=device_id):
            raise RuntimeError(f"Zone {zone_name} created but SOA not resolving after reload")

    def delete_zone(self, zone_name: str, device_id: Optional[int] = None):
        """Delete a zone file and remove its stanza from named.conf."""
        zone_file = self._zone_file_path(zone_name, device_id)
        self.backup_named_conf(device_id=device_id)
        named_conf = self.read_file(self._named_conf_path(device_id), device_id=device_id)
        updated = remove_zone_stanza(named_conf, zone_name)
        if updated == named_conf:
            logger.warning(
                'delete_zone(%s): named.conf has no matching zone stanza; '
                'removing the zone file only', zone_name,
            )
        else:
            self._write_named_conf_checked(
                updated, f"{self.named_conf}.bak", device_id=device_id,
            )
        for path in (
            self._zone_file_path(zone_name, device_id),
            self._zone_file_path(zone_name, device_id) + ".jnl",
        ):
            self._local_path(path).unlink(missing_ok=True)


# Singleton instance — file-backed when DEMO_MODE is on, SSH otherwise.
ssh_connector = DemoConnector() if settings.DEMO_MODE else SSHConnector()
