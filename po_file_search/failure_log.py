from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any


def log_failure(log_file: str | Path, event: str, error: BaseException | str, **context: Any) -> None:
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(error, BaseException):
        error_text = str(error)
        error_type = type(error).__name__
        tb = traceback.format_exception(type(error), error, error.__traceback__)
    else:
        error_text = str(error)
        error_type = "Error"
        tb = []
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        "error_type": error_type,
        "error": error_text,
        "context": context,
        "traceback": "".join(tb[-20:]),
    }
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
