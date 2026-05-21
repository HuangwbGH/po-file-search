from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from .config import MountConfig
from .platforms import SupportedOS, detect_os


class MountError(RuntimeError):
    pass


def mount_point_for(config: MountConfig, os_name: SupportedOS | None = None) -> Path:
    os_name = os_name or detect_os()
    if os_name == SupportedOS.LINUX:
        return Path(config.mount_point_linux)
    if os_name == SupportedOS.MACOS:
        return Path(config.mount_point_macos)
    raise MountError(f"Unsupported OS: {os_name}")


def is_mounted(mount_point: Path) -> bool:
    try:
        return subprocess.run(
            ["mountpoint", "-q", str(mount_point)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except FileNotFoundError:
        # macOS does not provide mountpoint by default.
        resolved = str(mount_point.resolve()) if mount_point.exists() else str(mount_point)
        output = subprocess.check_output(["mount"], text=True)
        return any(f" on {resolved} " in line or f" on {mount_point} " in line for line in output.splitlines())


def find_existing_smb_mount(config: MountConfig) -> Path | None:
    """Return an existing macOS SMB mount path for the configured share, if any."""
    try:
        output = subprocess.check_output(["mount"], text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    share_suffix = f"/{config.share}"
    for line in output.splitlines():
        if " on " not in line or " (smbfs" not in line:
            continue
        source, rest = line.split(" on ", 1)
        mount_path = rest.split(" (", 1)[0]
        if source.endswith(share_suffix):
            if config.username and f"//{config.username}@" not in source and f";{config.username}@" not in source:
                continue
            return Path(mount_path)
    return None


def _password(config: MountConfig) -> str | None:
    if not config.password_env:
        return None
    value = os.environ.get(config.password_env)
    if value is None:
        raise MountError(f"Environment variable {config.password_env} is not set")
    return value


def build_linux_mount_command(config: MountConfig, credentials_file: Path) -> list[str]:
    mount_point = mount_point_for(config, SupportedOS.LINUX)
    options = [
        f"credentials={credentials_file}",
        f"vers={config.smb_version}",
        "iocharset=utf8",
        "ro" if config.readonly else "rw",
    ]
    return ["mount", "-t", "cifs", config.unc, str(mount_point), "-o", ",".join(options)]


def _redact_command(command: list[str]) -> str:
    redacted = []
    for part in command:
        if part.startswith("//") and "@" in part:
            prefix, rest = part.split("@", 1)
            if ":" in prefix:
                user_prefix = prefix.split(":", 1)[0]
                part = f"{user_prefix}:***@{rest}"
        redacted.append(shlex.quote(part))
    return " ".join(redacted)


def build_macos_mount_command(config: MountConfig) -> list[str]:
    mount_point = mount_point_for(config, SupportedOS.MACOS)
    user_part = ""
    if config.username:
        password = _password(config)
        quoted_user = quote(config.username, safe="")
        if password:
            # macOS mount_smbfs accepts credentials only in the URL. Prefer a read-only NAS user.
            user_part = f"{quoted_user}:{quote(password, safe='')}@"
        else:
            user_part = f"{quoted_user}@"
    return ["mount_smbfs", f"//{user_part}{config.server}/{config.share}", str(mount_point)]


def ensure_mounted(config: MountConfig, dry_run: bool = False) -> Path:
    os_name = detect_os()
    mount_point = mount_point_for(config, os_name)

    if is_mounted(mount_point):
        return mount_point

    if os_name == SupportedOS.MACOS:
        existing = find_existing_smb_mount(config)
        if existing is not None:
            return existing

    mount_point.mkdir(parents=True, exist_ok=True)

    if os_name == SupportedOS.LINUX:
        if not config.username:
            raise MountError("Linux SMB mount requires username in config")
        password = _password(config)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fp:
            cred_path = Path(fp.name)
            fp.write(f"username={config.username}\n")
            if password is not None:
                fp.write(f"password={password}\n")
        cred_path.chmod(0o600)
        command = build_linux_mount_command(config, cred_path)
        if dry_run:
            print(" ".join(shlex.quote(part) for part in command))
            cred_path.unlink(missing_ok=True)
            return mount_point
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError:
            raise MountError(f"Linux mount failed: {_redact_command(command)}") from None
        finally:
            cred_path.unlink(missing_ok=True)
        return mount_point

    if os_name == SupportedOS.MACOS:
        command = build_macos_mount_command(config)
        if dry_run:
            safe_command = command.copy()
            if config.password_env and os.environ.get(config.password_env):
                safe_command[1] = safe_command[1].replace(quote(os.environ[config.password_env], safe=""), "***")
            print(" ".join(shlex.quote(part) for part in safe_command))
            return mount_point
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError:
            raise MountError(f"macOS mount failed: {_redact_command(command)}") from None
        return mount_point

    raise MountError(f"Unsupported OS: {os_name}")
