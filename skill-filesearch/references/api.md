# po-file-search API Reference

## Base URL

Default local MVP URL:

```text
http://192.168.88.20:18765
```

Override in shell:

```bash
export FILESEARCH_BASE_URL=http://your-host:18765
```

## Endpoints

### Health

```http
GET /health
```

Expected:

```json
{"ok": true}
```

### Search files

```http
POST /search_purchase_file
Content-Type: application/json
```

Request:

```json
{
  "query": "DCC1039S.pdf",
  "search_mode": "exact",
  "limit": 0,
  "user_id": "optional-user-id"
}
```

Response:

```json
{
  "matches": [
    {
      "file_id": 21559,
      "root_name": "采购共享/artwork",
      "file_name": "DCC1039S.pdf",
      "folder_path": "包装/纸箱/香港02",
      "extension": "pdf",
      "size": 11841579,
      "modified_time": 1310604290.5,
      "score": 0
    }
  ],
  "search_mode": "exact",
  "limit": 0
}
```

Search mode values:

- `smart`
- `left_contains`
- `right_contains`
- `contains`
- `exact`

`limit=0` means return all matches.

### Generate a download link

```http
POST /send_purchase_file
Content-Type: application/json
```

Request:

```json
{
  "file_id": 21559,
  "channel": "link",
  "user_id": "optional-user-id",
  "recipient": "optional-recipient"
}
```

Response:

```json
{
  "sent": false,
  "channel": "link",
  "file_id": 21559,
  "file_name": "DCC1039S.pdf",
  "download_url": "http://host:18765/download/token",
  "expire_minutes": 30,
  "expire_text": "30 minutes"
}
```

`expire_minutes=0` means the link never expires.

### Download

```http
GET /download/{token}
```

Returns the file stream or an error JSON.

## Manual index sync

Only run when asked by the user/admin:

```bash
cd /Users/mac/workspace/po-file-search
python3 -m po_file_search --config config.json index
```

Current policy: no background incremental sync; daily full sync runs at configured `index.full_sync_time` (default `23:23`) if enabled.

## Troubleshooting

- Health fails: service may not be running or base URL/port is wrong.
- Search misses a newly added file: local index may not have synced yet; run manual full sync if user requests.
- Link generation fails with file-not-found: index points to a file moved/deleted after last sync.
- Do not expose internal `full_path` in normal user responses.
