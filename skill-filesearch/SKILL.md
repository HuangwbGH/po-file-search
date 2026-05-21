---
name: skill-filesearch
description: Use this skill when the user wants to search files from the po-file-search MVP, find files by filename/folder name, generate download links, send a found file link through a channel, inspect search results, or operate the po-file-search HTTP API. This skill is for the local MVP service that indexes Synology SMB files and exposes /search_purchase_file, /send_purchase_file, and /download/{token}.
---

# Skill Filesearch

Use this skill to search the `po-file-search` MVP service and generate download links for files indexed from Synology SMB shares.

## Assumptions

- The MVP service is already deployed or runnable from `/Users/mac/workspace/po-file-search`.
- Default API base URL is `http://192.168.88.20:18765`; override with `FILESEARCH_BASE_URL` when needed.
- Search uses the service's local SQLite/FTS index, not live SMB scanning.
- If a user asks for a download link, generate a link with `send_purchase_file` after selecting the intended file.

## Core workflow

1. **Search** with `/search_purchase_file`.
2. **If multiple matches**, show concise numbered candidates and ask the user which one unless the user clearly requested all links.
3. **Generate link** with `/send_purchase_file` using the selected `file_id` and `channel=link`.
4. **Return only user-safe fields**: file name, folder path, size if useful, and download URL. Do not expose internal `full_path` unless the user is an admin/debugging.

## Search modes

Use these when the user specifies matching behavior:

| User wording | API value |
|---|---|
| 智能 / 默认 | `smart` |
| 左包含 / 以...开头 | `left_contains` |
| 右包含 / 以...结尾 | `right_contains` |
| 全包含 / 包含 | `contains` |
| 精准匹配 / 精确匹配 / 完全等于 | `exact` |

Use `limit=0` when the user asks for all matching results. Otherwise use service default or a small limit such as 10.

## Deterministic helper script

Prefer the bundled script for API calls:

```bash
python3 skill-filesearch/scripts/filesearch_client.py search 'DCC1039S.pdf' --mode exact --limit 0
python3 skill-filesearch/scripts/filesearch_client.py link 21559
python3 skill-filesearch/scripts/filesearch_client.py health
```

Set base URL if needed:

```bash
FILESEARCH_BASE_URL=http://host:18765 python3 skill-filesearch/scripts/filesearch_client.py search '关键词'
```

## API details

Read `references/api.md` when you need exact endpoint shapes, request examples, deployment assumptions, or troubleshooting notes.

## Safety and behavior

- Do not run a full index sync unless the user asks to sync/rebuild/update the index.
- Do not claim a file was sent to DingTalk unless the API call used `channel=dingtalk` and succeeded.
- If `/health` fails, report that the file-search service is not reachable and include the base URL checked.
- If search returns no matches, suggest trying `contains` mode or waiting for/triggering manual full sync if the file was just added.
