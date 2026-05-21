from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from .config import AppConfig


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    root_name TEXT NOT NULL,
    file_name TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    full_path TEXT NOT NULL UNIQUE,
    extension TEXT NOT NULL,
    size INTEGER NOT NULL,
    modified_time REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_name,
    folder_path,
    full_path UNINDEXED,
    content='files',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, file_name, folder_path, full_path)
    VALUES (new.id, new.file_name, new.folder_path, new.full_path);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, file_name, folder_path, full_path)
    VALUES('delete', old.id, old.file_name, old.folder_path, old.full_path);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, file_name, folder_path, full_path)
    VALUES('delete', old.id, old.file_name, old.folder_path, old.full_path);
    INSERT INTO files_fts(rowid, file_name, folder_path, full_path)
    VALUES (new.id, new.file_name, new.folder_path, new.full_path);
END;
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id TEXT,
    query TEXT,
    file_id INTEGER,
    recipient TEXT,
    channel TEXT,
    created_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS download_tokens (
    token TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL,
    user_id TEXT,
    expire_at REAL NOT NULL,
    used_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY(file_id) REFERENCES files(id)
);
CREATE TABLE IF NOT EXISTS directories (
    id INTEGER PRIMARY KEY,
    root_name TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    full_path TEXT NOT NULL UNIQUE,
    modified_time REAL NOT NULL,
    last_scanned_at REAL NOT NULL
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.executescript(SCHEMA)
    return con


def _ignored_dir(name: str, ignored_dirs: set[str]) -> bool:
    return name in ignored_dirs or name.startswith(".")


def _folder_path(root: Path, current_path: Path) -> str:
    return str(current_path.relative_to(root)) if current_path != root else ""


def _upsert_file(con: sqlite3.Connection, root_name: str, root: Path, full_path: Path) -> None:
    stat = full_path.stat()
    current_path = full_path.parent
    folder_path = _folder_path(root, current_path)
    con.execute(
        """
        INSERT INTO files(root_name, file_name, folder_path, full_path, extension, size, modified_time)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(full_path) DO UPDATE SET
            root_name=excluded.root_name,
            file_name=excluded.file_name,
            folder_path=excluded.folder_path,
            extension=excluded.extension,
            size=excluded.size,
            modified_time=excluded.modified_time
        """,
        (
            root_name,
            full_path.name,
            folder_path,
            str(full_path),
            full_path.suffix.lower().lstrip("."),
            stat.st_size,
            stat.st_mtime,
        ),
    )


def _upsert_directory(con: sqlite3.Connection, root_name: str, root: Path, directory: Path, stat_mtime: float) -> None:
    con.execute(
        """
        INSERT INTO directories(root_name, folder_path, full_path, modified_time, last_scanned_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(full_path) DO UPDATE SET
            root_name=excluded.root_name,
            folder_path=excluded.folder_path,
            modified_time=excluded.modified_time,
            last_scanned_at=excluded.last_scanned_at
        """,
        (root_name, _folder_path(root, directory), str(directory), stat_mtime, time.time()),
    )


def _sync_directory_files(con: sqlite3.Connection, root_name: str, root: Path, directory: Path) -> int:
    seen_files: set[str] = set()
    count = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0

    for item in entries:
        if not item.is_file() or item.name.startswith("."):
            continue
        try:
            _upsert_file(con, root_name, root, item)
        except OSError:
            continue
        seen_files.add(str(item))
        count += 1

    folder_path = _folder_path(root, directory)
    existing = con.execute(
        "SELECT full_path FROM files WHERE root_name = ? AND folder_path = ?",
        (root_name, folder_path),
    ).fetchall()
    stale_paths = [row[0] for row in existing if row[0] not in seen_files]
    if stale_paths:
        con.executemany("DELETE FROM files WHERE full_path = ?", [(path,) for path in stale_paths])
    return count


def index_root(con: sqlite3.Connection, root_name: str, root: Path, ignored_dirs: set[str]) -> int:
    """Full sync: scan all directories and reconcile deleted files/directories."""
    count = 0
    seen_paths: set[str] = set()
    seen_dirs: set[str] = set()
    for current, dirs, files in os.walk(root):
        dirs[:] = [item for item in dirs if not _ignored_dir(item, ignored_dirs)]
        current_path = Path(current)
        try:
            dir_stat = current_path.stat()
            _upsert_directory(con, root_name, root, current_path, dir_stat.st_mtime)
            seen_dirs.add(str(current_path))
        except OSError:
            continue
        for file_name in files:
            if file_name.startswith("."):
                continue
            full_path = current_path / file_name
            try:
                _upsert_file(con, root_name, root, full_path)
            except OSError:
                continue
            seen_paths.add(str(full_path))
            count += 1
            if count % 500 == 0:
                con.commit()

    con.commit()
    existing = con.execute("SELECT full_path FROM files WHERE root_name = ?", (root_name,)).fetchall()
    stale_paths = [row[0] for row in existing if row[0] not in seen_paths]
    if stale_paths:
        con.executemany("DELETE FROM files WHERE full_path = ?", [(path,) for path in stale_paths])

    existing_dirs = con.execute("SELECT full_path FROM directories WHERE root_name = ?", (root_name,)).fetchall()
    stale_dirs = [row[0] for row in existing_dirs if row[0] not in seen_dirs]
    if stale_dirs:
        con.executemany("DELETE FROM directories WHERE full_path = ?", [(path,) for path in stale_dirs])
    con.commit()
    return count


def incremental_index_root(con: sqlite3.Connection, root_name: str, root: Path, ignored_dirs: set[str]) -> int:
    """Incremental sync: walk directories, rescan only new or mtime-changed directories."""
    count = 0
    seen_dirs: set[str] = set()
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            stat = directory.stat()
            entries = list(directory.iterdir())
        except OSError:
            continue

        directory_text = str(directory)
        seen_dirs.add(directory_text)
        row = con.execute(
            "SELECT modified_time FROM directories WHERE full_path = ?",
            (directory_text,),
        ).fetchone()
        changed = row is None or float(row[0]) != float(stat.st_mtime)

        subdirs: list[Path] = []
        for item in entries:
            if item.is_dir() and not _ignored_dir(item.name, ignored_dirs):
                subdirs.append(item)
        stack.extend(reversed(subdirs))

        if changed:
            count += _sync_directory_files(con, root_name, root, directory)
            _upsert_directory(con, root_name, root, directory, stat.st_mtime)
            if count % 500 == 0:
                con.commit()

    existing_dirs = con.execute("SELECT full_path FROM directories WHERE root_name = ?", (root_name,)).fetchall()
    stale_dirs = [row[0] for row in existing_dirs if row[0] not in seen_dirs]
    if stale_dirs:
        for stale_dir in stale_dirs:
            con.execute("DELETE FROM files WHERE root_name = ? AND full_path LIKE ?", (root_name, f"{stale_dir}/%"))
            con.execute("DELETE FROM directories WHERE full_path = ?", (stale_dir,))
    con.commit()
    return count


def _scan_path(root, mounted_paths: dict[str, Path]) -> Path:
    if root.path:
        return Path(root.path)
    if root.path_from_mount:
        if root.path_from_mount not in mounted_paths:
            raise ValueError(f"No mounted path found for scan root: {root.path_from_mount}")
        path = mounted_paths[root.path_from_mount]
        if root.relative_path:
            path = path / root.relative_path
        return path
    raise ValueError(f"Scan root {root.name} must define path or path_from_mount")


def index_config(config: AppConfig, mounted_paths: dict[str, Path]) -> int:
    total = 0
    with connect(config.index_db) as con:
        for root in config.scan_roots:
            path = _scan_path(root, mounted_paths)
            if not path.exists():
                raise FileNotFoundError(f"Scan root does not exist: {path}")
            total += index_root(con, root.name, path, config.ignored_dirs)
    return total


def incremental_index_config(config: AppConfig, mounted_paths: dict[str, Path]) -> int:
    total = 0
    with connect(config.index_db) as con:
        for root in config.scan_roots:
            path = _scan_path(root, mounted_paths)
            if not path.exists():
                raise FileNotFoundError(f"Scan root does not exist: {path}")
            total += incremental_index_root(con, root.name, path, config.ignored_dirs)
    return total
