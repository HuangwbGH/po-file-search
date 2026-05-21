from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path

from .audit import log_event
from .config import AppConfig
from .downloads import create_download_token
from .indexer import connect
from .mounter import find_existing_smb_mount, mount_point_for


class SendError(RuntimeError):
    pass


def get_file_by_id(db_path: str | Path, file_id: int) -> dict[str, object] | None:
    with connect(db_path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT id, root_name, file_name, folder_path, full_path, extension, size, modified_time FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()
        return dict(row) if row else None


def _build_download_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/download/{token}"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _allowed_roots(config: AppConfig) -> list[Path]:
    roots: list[Path] = []
    mounted_paths = {}
    for mount in config.mounts:
        mounted_paths[mount.name] = find_existing_smb_mount(mount) or mount_point_for(mount)
    for scan_root in config.scan_roots:
        if scan_root.path:
            roots.append(Path(scan_root.path).resolve())
        elif scan_root.path_from_mount and scan_root.path_from_mount in mounted_paths:
            root_path = mounted_paths[scan_root.path_from_mount]
            if scan_root.relative_path:
                root_path = root_path / scan_root.relative_path
            roots.append(root_path.resolve())
    return roots


def _validate_allowed_path(config: AppConfig, full_path: Path) -> None:
    roots = _allowed_roots(config)
    if not roots:
        return
    resolved = full_path.resolve()
    if not any(_is_relative_to(resolved, root) for root in roots):
        raise SendError("File path is outside allowed scan roots")


def _send_dingtalk_webhook(webhook: str, title: str, text: str) -> None:
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text,
        },
    }
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status >= 400:
            raise SendError(f"DingTalk webhook returned HTTP {resp.status}")


def send_purchase_file(
    config: AppConfig,
    file_id: int,
    recipient: str | None = None,
    channel: str = "link",
    user_id: str | None = None,
) -> dict[str, object]:
    file_record = get_file_by_id(config.index_db, file_id)
    if not file_record:
        raise SendError(f"File id not found: {file_id}")

    full_path = Path(str(file_record["full_path"]))
    if not full_path.exists() or not full_path.is_file():
        raise SendError("File no longer exists. Please search again.")
    _validate_allowed_path(config, full_path)

    token = create_download_token(config.index_db, file_id, user_id, config.download.token_ttl_minutes)
    download_url = _build_download_url(config.download.base_url, token)

    if channel == "dingtalk":
        if not config.dingtalk.webhook_env:
            raise SendError("DingTalk webhook env is not configured")
        webhook = os.environ.get(config.dingtalk.webhook_env)
        if not webhook:
            raise SendError(f"Environment variable {config.dingtalk.webhook_env} is not set")
        title = f"采购文件：{file_record['file_name']}"
        expire_text = "永不过期" if config.download.token_ttl_minutes == 0 else f"{config.download.token_ttl_minutes} 分钟"
        text = (
            f"### 找到采购文件\n\n"
            f"- 文件名：{file_record['file_name']}\n"
            f"- 目录：{file_record['root_name']}/{file_record['folder_path']}\n"
            f"- 下载链接：[点击下载]({download_url})\n"
            f"- 有效期：{expire_text}"
        )
        _send_dingtalk_webhook(webhook, title, text)

    log_event(
        config.index_db,
        event_type="send",
        user_id=user_id,
        file_id=file_id,
        recipient=recipient,
        channel=channel,
        metadata={"download_url": download_url, "file_name": file_record["file_name"]},
    )
    return {
        "sent": channel == "dingtalk",
        "channel": channel,
        "file_id": file_id,
        "file_name": file_record["file_name"],
        "download_url": download_url,
        "expire_minutes": config.download.token_ttl_minutes,
        "expire_text": "never" if config.download.token_ttl_minutes == 0 else f"{config.download.token_ttl_minutes} minutes",
    }
