from __future__ import annotations

import sqlite3
from pathlib import Path

from .indexer import connect


SEARCH_MODE_ALIASES = {
    "smart": "smart",
    "智能": "smart",
    "contains": "contains",
    "full_contains": "contains",
    "全包含": "contains",
    "左包含": "left_contains",
    "left_contains": "left_contains",
    "startswith": "left_contains",
    "prefix": "left_contains",
    "右包含": "right_contains",
    "right_contains": "right_contains",
    "endswith": "right_contains",
    "suffix": "right_contains",
    "精准匹配": "exact",
    "精确匹配": "exact",
    "exact": "exact",
}


def normalize_search_mode(mode: str | None) -> str:
    key = (mode or "smart").strip()
    normalized = SEARCH_MODE_ALIASES.get(key)
    if not normalized:
        allowed = ", ".join(sorted(SEARCH_MODE_ALIASES))
        raise ValueError(f"Unsupported search mode: {mode}. Allowed: {allowed}")
    return normalized


def _terms(query: str) -> list[str]:
    return [token.strip() for token in query.replace("/", " ").split() if token.strip()]


def _fts_query(query: str) -> str:
    tokens = _terms(query)
    if not tokens:
        return ""
    return " AND ".join(f'"{token}"*' for token in tokens)


def _row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return dict(row)


def _limit_clause(limit: int) -> tuple[str, list[object]]:
    if limit > 0:
        return "LIMIT ?", [limit]
    return "", []


def _mode_pattern(query: str, mode: str) -> tuple[str, str]:
    if mode == "left_contains":
        return f"{query}%", "LIKE"
    if mode == "right_contains":
        return f"%{query}", "LIKE"
    if mode == "contains":
        return f"%{query}%", "LIKE"
    if mode == "exact":
        return query, "="
    raise ValueError(f"Unsupported explicit search mode: {mode}")


def _explicit_mode_search(con: sqlite3.Connection, query: str, limit: int, mode: str) -> list[dict[str, object]]:
    query = query.strip()
    if not query:
        return []
    pattern, operator = _mode_pattern(query, mode)
    limit_clause, limit_params = _limit_clause(limit)
    rows = con.execute(
        f"""
        SELECT id, root_name, file_name, folder_path, full_path, extension, size, modified_time, 0 AS rank
        FROM files
        WHERE file_name {operator} ? OR folder_path {operator} ?
        ORDER BY modified_time DESC
        {limit_clause}
        """,
        [pattern, pattern] + limit_params,
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _like_search(con: sqlite3.Connection, query: str, limit: int) -> list[dict[str, object]]:
    terms = _terms(query) or [query.strip()]
    terms = [term for term in terms if term]
    if not terms:
        return []

    where = " AND ".join(["(file_name LIKE ? OR folder_path LIKE ?)"] * len(terms))
    params: list[object] = []
    for term in terms:
        params.extend([f"%{term}%", f"%{term}%"])
    limit_clause, limit_params = _limit_clause(limit)
    params.extend(limit_params)

    rows = con.execute(
        f"""
        SELECT id, root_name, file_name, folder_path, full_path, extension, size, modified_time, 0 AS rank
        FROM files
        WHERE {where}
        ORDER BY modified_time DESC
        {limit_clause}
        """,
        params,
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _chunked_search(con: sqlite3.Connection, query: str, limit: int) -> list[dict[str, object]]:
    compact = "".join(_terms(query)) or query.strip()
    if len(compact) < 4:
        return []
    chunks = {compact[i : i + 2] for i in range(len(compact) - 1)}
    if not chunks:
        return []

    where = " OR ".join(["(file_name LIKE ? OR folder_path LIKE ?)"] * len(chunks))
    params: list[object] = []
    for chunk in chunks:
        params.extend([f"%{chunk}%", f"%{chunk}%"])

    rows = con.execute(
        f"""
        SELECT id, root_name, file_name, folder_path, full_path, extension, size, modified_time, 0 AS rank
        FROM files
        WHERE {where}
        LIMIT 200
        """,
        params,
    ).fetchall()

    scored: list[tuple[int, sqlite3.Row]] = []
    for row in rows:
        haystack = f"{row['file_name']} {row['folder_path']}"
        score = sum(1 for chunk in chunks if chunk in haystack)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -float(item[1]["modified_time"])))
    selected = scored[:limit] if limit > 0 else scored
    return [_row_to_dict(row) | {"rank": -score} for score, row in selected]


def search(db_path: str | Path, query: str, limit: int = 10, mode: str = "smart") -> list[dict[str, object]]:
    mode = normalize_search_mode(mode)
    if not query.strip():
        return []
    with connect(db_path) as con:
        con.row_factory = sqlite3.Row
        if mode != "smart":
            return _explicit_mode_search(con, query, limit, mode)

        fts = _fts_query(query)
        if not fts:
            return []
        limit_clause, limit_params = _limit_clause(limit)
        rows = con.execute(
            f"""
            SELECT
                files.id,
                files.root_name,
                files.file_name,
                files.folder_path,
                files.full_path,
                files.extension,
                files.size,
                files.modified_time,
                bm25(files_fts) AS rank
            FROM files_fts
            JOIN files ON files.id = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY rank
            {limit_clause}
            """,
            [fts] + limit_params,
        ).fetchall()
        if rows:
            return [_row_to_dict(row) for row in rows]

        rows = _like_search(con, query, limit)
        if rows:
            return rows
        return _chunked_search(con, query, limit)
