from __future__ import annotations

import argparse
import json
import mimetypes
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .audit import log_event
from .config import AppConfig, load_config
from .downloads import get_download_file
from .failure_log import log_failure
from .searcher import search
from .sender import SendError, send_purchase_file
from .scheduler import start_index_scheduler


class ApiHandler(BaseHTTPRequestHandler):
    config: AppConfig

    def _json(self, status: int, payload: dict[str, object] | list[object]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True})
            return

        if self.path.startswith("/download/"):
            token = unquote(self.path.removeprefix("/download/").split("?", 1)[0])
            item = get_download_file(self.config.index_db, token)
            if not item:
                log_failure(self.config.logging.failure_log_file, "download_token_invalid", "download token not found or expired", token=token)
                self._json(404, {"error": "download token not found or expired"})
                return
            path = Path(str(item["full_path"]))
            if not path.exists() or not path.is_file():
                log_failure(self.config.logging.failure_log_file, "download_file_not_found", "file not found", token=token, path=str(path))
                self._json(404, {"error": "file not found"})
                return
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
            self.end_headers()
            with path.open("rb") as fp:
                while True:
                    chunk = fp.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            log_event(
                self.config.index_db,
                event_type="download",
                user_id=str(item.get("user_id") or "") or None,
                file_id=int(item["file_id"]),
            )
            return

        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/search_purchase_file":
                body = self._read_json()
                query = str(body.get("query", "")).strip()
                limit = self.config.max_results if body.get("limit") is None else int(body.get("limit"))
                user_id = str(body.get("user_id", "")).strip() or None
                mode = str(body.get("search_mode") or body.get("mode") or self.config.search_mode)
                rows = search(self.config.index_db, query, limit=limit, mode=mode)
                matches = [_public_match(row) for row in rows]
                log_event(
                    self.config.index_db,
                    event_type="search",
                    user_id=user_id,
                    query=query,
                    metadata={"result_count": len(matches)},
                )
                self._json(200, {"matches": matches, "search_mode": mode, "limit": limit})
                return

            if self.path == "/send_purchase_file":
                body = self._read_json()
                file_id = int(body["file_id"])
                result = send_purchase_file(
                    self.config,
                    file_id=file_id,
                    recipient=str(body.get("recipient", "")).strip() or None,
                    channel=str(body.get("channel", "link")),
                    user_id=str(body.get("user_id", "")).strip() or None,
                )
                self._json(200, result)
                return

            self._json(404, {"error": "not found"})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            log_failure(self.config.logging.failure_log_file, "bad_request", exc, path=self.path)
            self._json(400, {"error": str(exc)})
        except SendError as exc:
            log_failure(self.config.logging.failure_log_file, "send_failed", exc, path=self.path)
            self._json(409, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive API boundary
            log_failure(self.config.logging.failure_log_file, "api_unhandled_error", exc, path=self.path)
            self._json(500, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return


def _public_match(row: dict[str, object]) -> dict[str, object]:
    return {
        "file_id": row["id"],
        "root_name": row["root_name"],
        "file_name": row["file_name"],
        "folder_path": row["folder_path"],
        "extension": row["extension"],
        "size": row["size"],
        "modified_time": row["modified_time"],
        "score": row.get("rank"),
    }


def run_server(config: AppConfig) -> None:
    ApiHandler.config = config
    start_index_scheduler(config)
    httpd = ThreadingHTTPServer((config.server.host, config.server.port), ApiHandler)
    print(f"po-file-search server listening on {config.server.host}:{config.server.port}")
    if config.index.auto_full_sync_enabled:
        print(
            f"full index scheduler enabled: daily_at={config.index.full_sync_time}, "
            f"full_sync_on_startup={config.index.full_sync_on_startup}",
            flush=True,
        )
    else:
        print("full index scheduler disabled", flush=True)
    httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(prog="po-file-search-server")
    parser.add_argument("--config", default="config.example.json")
    args = parser.parse_args()
    run_server(load_config(args.config))


if __name__ == "__main__":
    main()
