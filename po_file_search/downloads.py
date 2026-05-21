from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path

from .indexer import connect


def create_download_token(db_path: str | Path, file_id: int, user_id: str | None, ttl_minutes: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    expire_at = 0 if ttl_minutes == 0 else now + ttl_minutes * 60
    with connect(db_path) as con:
        con.execute(
            """
            INSERT INTO download_tokens(token, file_id, user_id, expire_at, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (token, file_id, user_id, expire_at, now),
        )
        con.commit()
    return token


def get_download_file(db_path: str | Path, token: str) -> dict[str, object] | None:
    now = time.time()
    with connect(db_path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            SELECT download_tokens.token, download_tokens.file_id, download_tokens.user_id,
                   download_tokens.expire_at, files.file_name, files.full_path, files.size
            FROM download_tokens
            JOIN files ON files.id = download_tokens.file_id
            WHERE download_tokens.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if float(row["expire_at"]) > 0 and float(row["expire_at"]) < now:
            return None
        con.execute("UPDATE download_tokens SET used_at = ? WHERE token = ? AND used_at IS NULL", (now, token))
        con.commit()
        return dict(row)
