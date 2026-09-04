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
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import paramiko
from app.config import settings

logger = logging.getLogger(__name__)


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
            if f.startswith("db.external.") and not f.endswith(".jnl") and ".bak." not in f
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
        self.backup_named_conf(device_id=device_id)
        named_conf = self.read_file(named_conf_path, device_id=device_id)
        stanza = (
            f'\n    zone "{zone_name}." {{\n'
            f'        type master;\n'
            f'        file "db.external.{zone_name}.";\n'
            f'        allow-update {{\n'
            f'            localhost;\n'
            f'        }};\n'
            f'    }};\n'
        )
        if 'view "external"' in named_conf:
            named_conf = named_conf.rstrip()
            if named_conf.endswith('};'):
                named_conf = named_conf[:-2] + stanza + '};'
        self.write_file(named_conf_path, named_conf, device_id=device_id)

        self.reconfig_named(device_id=device_id)

        for i in range(5):
            time.sleep(0.5)
            result = self.dig_query(f"{zone_name} SOA", device_id=device_id)
            if result:
                return
        raise RuntimeError(f"Zone {zone_name} created but SOA not resolving after reload")

    def delete_zone(self, zone_name: str, device_id: Optional[int] = None):
        """Delete a zone file and remove from named.conf."""
        named_conf_path = self._named_conf_path(device_id)
        zone_file = self._zone_file_path(zone_name, device_id)

        self.backup_named_conf(device_id=device_id)
        named_conf = self.read_file(named_conf_path, device_id=device_id)
        pattern = rf'\n\s*zone\s+"{re.escape(zone_name)}\."\s*\{{[^}}]*\}};'
        named_conf = re.sub(pattern, '', named_conf, flags=re.DOTALL)
        self.write_file(named_conf_path, named_conf, device_id=device_id)
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


# Singleton instance
ssh_connector = SSHConnector()
