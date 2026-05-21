from __future__ import annotations

import json
import time
from pathlib import Path

from .indexer import connect


def log_event(
    db_path: str | Path,
    event_type: str,
    user_id: str | None = None,
    query: str | None = None,
    file_id: int | None = None,
    recipient: str | None = None,
    channel: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    with connect(db_path) as con:
        con.execute(
            """
            INSERT INTO audit_logs(event_type, user_id, query, file_id, recipient, channel, created_at, metadata)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                user_id,
                query,
                file_id,
                recipient,
                channel,
                time.time(),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        con.commit()
