from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MountConfig:
    name: str
    server: str
    share: str
    mount_point_linux: str
    mount_point_macos: str
    username: str | None = None
    password_env: str | None = None
    readonly: bool = True
    smb_version: str = "3.0"

    @property
    def unc(self) -> str:
        return f"//{self.server}/{self.share}"


@dataclass(frozen=True)
class ScanRoot:
    name: str
    path_from_mount: str | None = None
    relative_path: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 18765


@dataclass(frozen=True)
class DownloadConfig:
    base_url: str = "http://127.0.0.1:18765"
    token_ttl_minutes: int = 30


@dataclass(frozen=True)
class DingtalkConfig:
    webhook_env: str | None = None


@dataclass(frozen=True)
class IndexConfig:
    auto_full_sync_enabled: bool = True
    full_sync_time: str = "23:23"
    full_sync_on_startup: bool = False


@dataclass(frozen=True)
class AppConfig:
    mounts: list[MountConfig]
    index_db: str
    scan_roots: list[ScanRoot]
    ignored_dirs: set[str]
    max_results: int = 10
    search_mode: str = "smart"
    server: ServerConfig = field(default_factory=ServerConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    dingtalk: DingtalkConfig = field(default_factory=DingtalkConfig)
    index: IndexConfig = field(default_factory=IndexConfig)


def load_config(path: str | Path) -> AppConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    mounts = [MountConfig(**item) for item in raw.get("mounts", [])]
    scan_roots = [ScanRoot(**item) for item in raw.get("scan_roots", [])]
    return AppConfig(
        mounts=mounts,
        index_db=raw.get("index_db", "./data/file_index.sqlite"),
        scan_roots=scan_roots,
        ignored_dirs=set(raw.get("ignored_dirs", [])),
        max_results=int(raw.get("max_results", 10)),
        search_mode=raw.get("search_mode", "smart"),
        server=ServerConfig(**raw.get("server", {})),
        download=DownloadConfig(**raw.get("download", {})),
        dingtalk=DingtalkConfig(**raw.get("dingtalk", {})),
        index=IndexConfig(**raw.get("index", {})),
    )


def config_dir(path: str | Path) -> Path:
    return Path(path).resolve().parent
