from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .failure_log import log_failure
from .indexer import index_config
from .mounter import ensure_mounted, mount_point_for
from .platforms import detect_os
from .searcher import search
from .server import run_server


def _mount_all(config_path: str, dry_run: bool = False) -> dict[str, Path]:
    config = load_config(config_path)
    mounted: dict[str, Path] = {}
    for mount in config.mounts:
        mounted[mount.name] = ensure_mounted(mount, dry_run=dry_run)
    return mounted


def main() -> None:
    parser = argparse.ArgumentParser(prog="po-file-search")
    parser.add_argument("--config", default="config.example.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("detect-os")

    mount_parser = sub.add_parser("mount")
    mount_parser.add_argument("--dry-run", action="store_true")

    index_parser = sub.add_parser("index")
    index_parser.add_argument("--no-mount", action="store_true")

    search_parser = sub.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int)
    search_parser.add_argument("--mode", default=None, help="smart/contains/left_contains/right_contains/exact or 中文别名")

    sub.add_parser("serve")

    args = parser.parse_args()

    if args.command == "detect-os":
        print(detect_os().value)
        return

    config = load_config(args.config)

    if args.command == "mount":
        try:
            mounted = _mount_all(args.config, dry_run=args.dry_run)
        except Exception as exc:
            log_failure(config.logging.failure_log_file, "mount_failed", exc, dry_run=args.dry_run)
            raise
        print(json.dumps({k: str(v) for k, v in mounted.items()}, ensure_ascii=False, indent=2))
        return

    if args.command == "index":
        mounted = {mount.name: mount_point_for(mount) for mount in config.mounts} if args.no_mount else _mount_all(args.config)
        try:
            total = index_config(config, mounted)
        except Exception as exc:
            log_failure(config.logging.failure_log_file, "manual_full_index_failed", exc)
            raise
        print(json.dumps({"indexed": total}, ensure_ascii=False))
        return

    if args.command == "search":
        limit = config.max_results if args.limit is None else args.limit
        rows = search(config.index_db, args.query, limit=limit, mode=args.mode or config.search_mode)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if args.command == "serve":
        run_server(config)
        return


if __name__ == "__main__":
    main()
