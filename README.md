# po-file-search

## 目录

- [功能介绍](#功能介绍)
- [当前已实现功能](#当前已实现功能)
- [运行环境](#运行环境)
- [配置文件参数说明](#配置文件参数说明)
- [如何使用](#如何使用)
- [HTTP API 使用](#http-api-使用)
- [程序部署方式](#程序部署方式)
- [索引同步策略](#索引同步策略)
- [常用命令](#常用命令)
- [项目结构](#项目结构)
- [文档](#文档)
- [注意事项](#注意事项)
- [后续增强](#后续增强)

## 功能介绍

`po-file-search` 是采购文件搜索 MVP 服务，用于让 OpenClaw 通过对话方式，从群晖 SMB 文件服务器中按文件夹名称和文件名称快速找到文件，并生成可发送给用户的下载链接。

核心链路：

```text
群晖 SMB 共享目录
  ↓ 挂载到 Linux/macOS
手动或每日定时全量扫描文件名/文件夹名
  ↓
OpenClaw 服务器本地 SQLite/FTS 索引
  ↓
OpenClaw/HTTP API 搜索
  ↓
生成下载 token 和下载链接
  ↓
通过钉钉等渠道发送给用户
```

重要原则：

- 搜索时查询本地 SQLite/FTS 索引，不依赖群晖搜索。
- 用户每次搜索时不重新扫描群晖。
- 当前暂行同步策略只保留每日低频全量同步和手动全量同步。
- 发送或下载阶段才读取群晖真实文件。
- 下载链接使用可配置的对外 IP/域名和端口，不使用 `127.0.0.1` 发给用户。

## 当前已实现功能

1. **跨平台系统识别**：支持 Linux 和 macOS。
2. **群晖 SMB 挂载**：Linux 使用 CIFS；macOS 可复用 Finder 已挂载 SMB 共享。
3. **子目录扫描**：支持挂载共享目录后只扫描指定子目录。
4. **本地索引**：使用 SQLite + FTS5 保存文件元数据和搜索索引。
5. **文件搜索**：支持 CLI 和 HTTP API。
6. **搜索结果数量配置**：`max_results = 0` 表示返回全部。
7. **搜索模式配置**：支持智能、左包含、右包含、全包含、精准匹配。
8. **下载链接**：支持生成下载 token 和下载链接。
9. **下载有效期配置**：`token_ttl_minutes = 0` 表示永不过期。
10. **每日定时全量同步**：默认每天 `23:23` 执行一次，可配置。
11. **手动全量同步**：管理员可随时执行全量同步。
12. **HTTP 服务**：提供健康检查、搜索、生成链接、下载接口。
13. **基础审计日志**：记录搜索、生成链接、下载事件。
14. **钉钉 webhook 骨架**：可通过 webhook 发送链接消息。
15. **Docker 文件**：提供 `Dockerfile` 和 `docker-compose.yml`。

## 运行环境

### Linux 生产环境

- Python 3.9+
- SQLite FTS5
- `cifs-utils`
- 可访问群晖 SMB 服务

安装 CIFS：

```bash
sudo apt-get install -y cifs-utils
```

### macOS 开发环境

- Python 3.9+
- 系统自带 `mount_smbfs`
- 可通过 Finder 或命令行访问群晖 SMB

macOS 推荐先用 Finder 挂载共享目录，再让程序复用 Finder 挂载路径。

## 配置文件参数说明

配置文件：

```text
config.json
```

示例：

```json
{
  "mounts": [
    {
      "name": "采购共享",
      "server": "192.168.1.26",
      "share": "X.artwork2",
      "mount_point_linux": "/mnt/synology/purchase",
      "mount_point_macos": "/Volumes/采购共享",
      "username": "cg-name_search",
      "password_env": "searchpassword",
      "readonly": true,
      "smb_version": "3.0"
    }
  ],
  "index_db": "./data/file_index.sqlite",
  "scan_roots": [
    {
      "name": "采购共享/artwork",
      "path_from_mount": "采购共享",
      "relative_path": "artwork"
    }
  ],
  "ignored_dirs": ["@eaDir", "#recycle", ".snapshot"],
  "max_results": 10,
  "search_mode": "smart",
  "server": {
    "host": "0.0.0.0",
    "port": 18765
  },
  "download": {
    "base_url": "http://192.168.88.20:18765",
    "token_ttl_minutes": 30
  },
  "dingtalk": {
    "webhook_env": "DINGTALK_WEBHOOK"
  },
  "index": {
    "auto_full_sync_enabled": true,
    "full_sync_time": "23:23",
    "full_sync_on_startup": false
  }
}
```

### mounts

| 参数 | 必填 | 说明 |
|---|---:|---|
| `name` | 是 | 挂载名称，供 `scan_roots[].path_from_mount` 引用 |
| `server` | 是 | 群晖 IP、主机名或域名 |
| `share` | 是 | SMB 共享文件夹名，不是子目录 |
| `mount_point_linux` | 是 | Linux 挂载点 |
| `mount_point_macos` | 是 | macOS 挂载点 |
| `username` | 是 | 群晖只读账号 |
| `password_env` | 是 | 密码所在环境变量名，不是密码明文 |
| `readonly` | 否 | 是否只读挂载，建议 `true` |
| `smb_version` | 否 | SMB 协议版本，默认 `3.0` |

### scan_roots

| 参数 | 必填 | 说明 |
|---|---:|---|
| `name` | 是 | 扫描根名称，写入索引的 `root_name` |
| `path_from_mount` | 否 | 引用 `mounts[].name` |
| `relative_path` | 否 | 挂载目录下要扫描的子目录，空字符串表示扫描挂载根目录 |
| `path` | 否 | 直接指定本地路径，用于测试或特殊场景 |

例如真实路径：

```text
\\192.168.1.26\X.artwork2\artwork
```

配置方式：

```json
"share": "X.artwork2",
"relative_path": "artwork"
```

### 搜索配置

| 参数 | 说明 |
|---|---|
| `max_results` | 默认搜索结果数量；大于 0 表示最多返回 N 条，等于 0 表示返回全部 |
| `search_mode` | 默认搜索模式，可被 CLI `--mode` 或 HTTP `search_mode` 覆盖 |

搜索模式：

| 模式 | 中文别名 | 含义 |
|---|---|---|
| `smart` | `智能` | 智能搜索，先 FTS，再 LIKE/中文切片兜底 |
| `left_contains` | `左包含` | 文件名或目录以关键词开头 |
| `right_contains` | `右包含` | 文件名或目录以关键词结尾 |
| `contains` | `全包含` | 文件名或目录包含关键词 |
| `exact` | `精准匹配` / `精确匹配` | 文件名或目录完全等于关键词 |

### HTTP 服务配置

| 参数 | 说明 |
|---|---|
| `server.host` | HTTP 服务监听地址，生产建议 `0.0.0.0` |
| `server.port` | HTTP 服务监听端口，可配置 |

### 下载链接配置

| 参数 | 说明 |
|---|---|
| `download.base_url` | 生成给用户访问的对外下载地址，可配置 IP 或域名 |
| `download.token_ttl_minutes` | 下载链接有效期，单位分钟；大于 0 表示 N 分钟过期，等于 0 表示永不过期 |

注意：发给用户的下载链接不要使用 `127.0.0.1`。

### 钉钉配置

| 参数 | 说明 |
|---|---|
| `dingtalk.webhook_env` | 钉钉 webhook 地址所在环境变量名 |

### 索引同步配置

| 参数 | 说明 |
|---|---|
| `index.auto_full_sync_enabled` | 是否启用每日定时全量同步 |
| `index.full_sync_time` | 每日全量同步时间，格式 `HH:MM`，默认 `23:23` |
| `index.full_sync_on_startup` | 服务启动后是否立即执行一次全量同步 |

当前暂行策略：

- 删除后台增量同步。
- 每天 `23:23` 做一次全量同步。
- 管理员可手动执行全量同步。

## 如何使用

### 1. 设置密码环境变量

`password_env` 填的是环境变量名，不是密码。

例如配置：

```json
"password_env": "searchpassword"
```

运行前设置：

```bash
export searchpassword='你的群晖密码'
```

### 2. macOS 先人工挂载群晖

Finder 中访问：

```text
smb://192.168.1.26/X.artwork2
```

登录成功后，程序会自动复用 Finder 挂载路径。

### 3. 检测系统

```bash
python3 -m po_file_search --config config.json detect-os
```

### 4. 检查或复用挂载

```bash
python3 -m po_file_search --config config.json mount
```

### 5. 手动全量同步索引

```bash
python3 -m po_file_search --config config.json index
```

### 6. 搜索文件

默认搜索：

```bash
python3 -m po_file_search --config config.json search 'DCC1039S.pdf'
```

返回全部匹配：

```bash
python3 -m po_file_search --config config.json search 'DCC1039S.pdf' --limit 0
```

指定搜索模式：

```bash
python3 -m po_file_search --config config.json search 'DCC1039S.pdf' --mode exact --limit 0
```

### 7. 启动 HTTP 服务

```bash
python3 -m po_file_search --config config.json serve
```

后台启动示例：

```bash
nohup env searchpassword='你的群晖密码' \
  python3 -m po_file_search --config config.json serve \
  > /tmp/po-file-search-server.log 2>&1 &
```

## HTTP API 使用

### 健康检查

```bash
curl http://192.168.88.20:18765/health
```

### 搜索文件

```bash
curl -X POST http://192.168.88.20:18765/search_purchase_file \
  -H 'Content-Type: application/json' \
  -d '{"query":"DCC1039S.pdf","search_mode":"exact","limit":0}'
```

参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `query` | 是 | 搜索关键词 |
| `limit` | 否 | 返回数量，`0` 表示全部，不传则使用 `max_results` |
| `search_mode` | 否 | 搜索模式，不传则使用配置中的 `search_mode` |
| `mode` | 否 | `search_mode` 的别名 |
| `user_id` | 否 | 审计用用户 ID |

### 生成下载链接

```bash
curl -X POST http://192.168.88.20:18765/send_purchase_file \
  -H 'Content-Type: application/json' \
  -d '{"file_id":21559,"channel":"link","user_id":"test-user"}'
```

参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `file_id` | 是 | 搜索结果中的文件 ID |
| `channel` | 否 | `link` 仅生成链接；`dingtalk` 通过 webhook 发送 |
| `recipient` | 否 | 接收人或群 ID，审计用 |
| `user_id` | 否 | 操作用户 ID，审计用 |

### 下载文件

浏览器打开返回的 `download_url` 即可下载。

## 程序部署方式

### 方式一：本机直接运行

适合开发和 MVP 验证。

```bash
cp config.example.json config.json
export searchpassword='你的群晖密码'
python3 -m po_file_search --config config.json mount
python3 -m po_file_search --config config.json index
python3 -m po_file_search --config config.json serve
```

### 方式二：后台运行

```bash
nohup env searchpassword='你的群晖密码' \
  python3 -m po_file_search --config config.json serve \
  > /tmp/po-file-search-server.log 2>&1 &
```

停止：

```bash
pkill -f 'python3 -m po_file_search --config config.json serve'
```

### 方式三：Docker 部署

```bash
docker compose up -d --build
```

推荐生产方式：宿主机挂载群晖 SMB，容器通过只读 volume 读取挂载目录。

### 方式四：Linux 生产建议

1. 使用只读群晖账号。
2. 使用 systemd/fstab 或运维脚本完成 SMB 挂载。
3. 使用本服务运行 HTTP API。
4. 通过 `index.auto_full_sync_enabled` 和 `index.full_sync_time` 控制每日全量同步。
5. `download.base_url` 配置为内网可访问 IP 或 HTTPS 域名。

## 索引同步策略

当前暂行方案：

```text
每天 23:23 全量同步一次，可配置
不做后台增量同步
支持管理员手动全量同步
```

原因：当前 92,108 个文件实测：

| 同步类型 | 耗时 |
|---|---:|
| 全量同步 | 约 289 秒 |
| 无变化目录级增量同步 | 约 291 秒 |

结论：瓶颈主要是 SMB 目录遍历/扫描，不是 SQLite 写入。因此后台增量同步暂时删除，避免白天频繁压 NAS。

手动全量同步：

```bash
python3 -m po_file_search --config config.json index
```

调整每日同步时间：

```json
"index": {
  "auto_full_sync_enabled": true,
  "full_sync_time": "23:23",
  "full_sync_on_startup": false
}
```

关闭每日同步：

```json
"index": {
  "auto_full_sync_enabled": false,
  "full_sync_time": "23:23",
  "full_sync_on_startup": false
}
```

## 常用命令

```bash
# 语法检查
python3 -m compileall po_file_search tests

# 检测系统
python3 -m po_file_search --config config.json detect-os

# 预览挂载命令
python3 -m po_file_search --config config.json mount --dry-run

# 确保挂载或复用已有挂载
python3 -m po_file_search --config config.json mount

# 手动全量同步索引
python3 -m po_file_search --config config.json index

# 搜索文件
python3 -m po_file_search --config config.json search '关键词'

# 搜索并返回全部结果
python3 -m po_file_search --config config.json search '关键词' --limit 0

# 指定搜索模式
python3 -m po_file_search --config config.json search '关键词' --mode exact

# 启动 HTTP API 服务
python3 -m po_file_search --config config.json serve

# Docker 启动
docker compose up -d --build
```

## 项目结构

```text
po-file-search/
  README.md
  AGENTS.md
  config.example.json
  requirements.txt
  Dockerfile
  docker-compose.yml
  data/
    .gitkeep
  docs/
    PRD.md
    DatabaseSchema.md
  po_file_search/
    __init__.py
    __main__.py
    audit.py
    cli.py
    config.py
    downloads.py
    indexer.py
    mounter.py
    platforms.py
    scheduler.py
    searcher.py
    sender.py
    server.py
  tests/
    test_basic.py
```

## 文档

- 产品需求文档：[docs/PRD.md](./docs/PRD.md)
- 数据库说明文档：[docs/DatabaseSchema.md](./docs/DatabaseSchema.md)

## 注意事项

1. `share` 必须是 SMB 共享文件夹名，不是子目录。
2. 如果要扫描共享文件夹下的子目录，用 `scan_roots[].relative_path`。
3. `password_env` 是环境变量名，不是密码明文。
4. 下载链接发给用户时不要使用 `127.0.0.1`。
5. macOS 本地调试推荐先用 Finder 挂载 SMB。
6. 搜索结果中的真实 `full_path` 只用于服务内部，不应直接暴露给普通用户。
7. 当前钉钉能力是 webhook 消息骨架，不是完整钉钉内部应用文件上传。
8. 当前不做后台增量同步。

## 后续增强

- 群晖 File Station API / Universal Search PoC，减少 SMB 扫描。
- 手动刷新指定目录。
- 业务上传事件触发局部刷新。
- 企业级权限系统接入。
- 钉钉内部应用文件上传/单聊发送。
- 文件正文搜索。
