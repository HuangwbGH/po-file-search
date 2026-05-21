#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://192.168.88.20:18765"


def request_json(base_url: str, method: str, path: str, payload: dict | None = None) -> dict:
    url = base_url.rstrip("/") + path
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {url}: {raw}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach {url}: {exc.reason}") from None
    except socket.timeout:
        raise SystemExit(f"Timeout calling {url}") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="Client for po-file-search MVP API")
    parser.add_argument("--base-url", default=os.environ.get("FILESEARCH_BASE_URL", DEFAULT_BASE_URL))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--mode", "--search-mode", dest="search_mode", default=None)
    search.add_argument("--limit", type=int, default=None)
    search.add_argument("--user-id", default=None)

    link = sub.add_parser("link")
    link.add_argument("file_id", type=int)
    link.add_argument("--channel", default="link")
    link.add_argument("--user-id", default=None)
    link.add_argument("--recipient", default=None)

    args = parser.parse_args()

    if args.command == "health":
        result = request_json(args.base_url, "GET", "/health")
    elif args.command == "search":
        payload = {"query": args.query}
        if args.search_mode is not None:
            payload["search_mode"] = args.search_mode
        if args.limit is not None:
            payload["limit"] = args.limit
        if args.user_id is not None:
            payload["user_id"] = args.user_id
        result = request_json(args.base_url, "POST", "/search_purchase_file", payload)
    elif args.command == "link":
        payload = {"file_id": args.file_id, "channel": args.channel}
        if args.user_id is not None:
            payload["user_id"] = args.user_id
        if args.recipient is not None:
            payload["recipient"] = args.recipient
        result = request_json(args.base_url, "POST", "/send_purchase_file", payload)
    else:
        raise AssertionError(args.command)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
