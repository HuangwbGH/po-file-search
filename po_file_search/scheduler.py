from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import AppConfig
from .failure_log import log_failure
from .indexer import index_config
from .mounter import ensure_mounted


def _mount_all(config: AppConfig) -> dict[str, Path]:
    return {mount.name: ensure_mounted(mount) for mount in config.mounts}


def run_full_index_once(config: AppConfig) -> int:
    mounted = _mount_all(config)
    return index_config(config, mounted)


def start_index_scheduler(config: AppConfig) -> threading.Thread | None:
    if not config.index.auto_full_sync_enabled:
        return None

    def loop() -> None:
        if config.index.full_sync_on_startup:
            _safe_full_index(config)
        next_full = _next_full_sync_timestamp(config.index.full_sync_time)
        while True:
            now = time.time()
            time.sleep(max(1, next_full - now))
            _safe_full_index(config)
            next_full = _next_full_sync_timestamp(config.index.full_sync_time, after=datetime.now() + timedelta(seconds=1))

    thread = threading.Thread(target=loop, name="po-file-search-full-index-scheduler", daemon=True)
    thread.start()
    return thread


def _next_full_sync_timestamp(full_sync_time: str, after: datetime | None = None) -> float:
    after = after or datetime.now()
    hour_text, minute_text = full_sync_time.split(":", 1)
    target = after.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
    if target <= after:
        target += timedelta(days=1)
    return target.timestamp()


def _safe_full_index(config: AppConfig) -> None:
    try:
        started = time.time()
        total = run_full_index_once(config)
        elapsed = time.time() - started
        print(f"full index sync completed: {total} files, elapsed={elapsed:.2f}s", flush=True)
    except Exception as exc:  # pragma: no cover - background safety boundary
        log_failure(config.logging.failure_log_file, "full_index_sync_failed", exc)
        print(f"full index sync failed: {exc}", flush=True)
