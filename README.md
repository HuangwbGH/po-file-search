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
  },
  "logging": {
    "failure_log_file": "./logs/po-file-search-error.log"
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

### 失败运行日志配置

当前运行日志只记录失败事件，不记录成功请求。

```json
"logging": {
  "failure_log_file": "./logs/po-file-search-error.log"
}
```

会记录的失败事件包括：

- 挂载失败。
- 手动全量同步失败。
- 每日全量同步失败。
- HTTP API 参数错误。
- 生成下载链接失败。
- 下载 token 无效或过期。
- 下载文件不存在。
- 未处理异常。

日志格式为 JSON Lines，每行一条失败记录，包含时间、事件类型、错误类型、错误信息、上下文和异常堆栈。

### 索引同步配置

| 参数 | 说明 |
|---|---|
| `index.auto_full_sync_enabled` | 是否启用每日定时全量同步 |
| `index.full_sync_time` | 每日全量同步时间，格式 `HH:MM`，默认 `23:23` |
| `index.full_sync_on_startup` | 服务启动后是否立即执行一次全量同步 |
| `logging.failure_log_file` | 失败运行日志文件路径，只记录失败事件 |

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


## LinuxOS 部署详细步骤

本节说明在 LinuxOS 上部署 `po-file-search` 的完整步骤。

### 1. 安装系统依赖

Debian / Ubuntu：

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip cifs-utils curl
```

CentOS / Rocky Linux / RHEL：

```bash
sudo yum install -y python3 python3-pip cifs-utils curl
```

说明：

| 依赖 | 用途 |
|---|---|
| `python3` | 运行程序 |
| `cifs-utils` | 挂载群晖 SMB 共享目录 |
| `curl` | 测试 HTTP API |
| SQLite FTS5 | Python 标准库 `sqlite3` 通常已包含，用于本地索引 |

检查 Python：

```bash
python3 --version
```

### 2. 准备项目目录

进入项目目录：

```bash
cd /opt/po-file-search
```

如果是从当前代码复制到 Linux，确保目录结构类似：

```text
po-file-search/
  README.md
  config.example.json
  po_file_search/
  docs/
  data/
```

### 3. 准备配置文件

```bash
cp config.example.json config.json
```

Linux 重点配置示例：

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
  "scan_roots": [
    {
      "name": "采购共享/artwork",
      "path_from_mount": "采购共享",
      "relative_path": "artwork"
    }
  ],
  "server": {
    "host": "0.0.0.0",
    "port": 18765
  },
  "download": {
    "base_url": "http://Linux服务器IP或域名:18765",
    "token_ttl_minutes": 30
  },
  "index": {
    "auto_full_sync_enabled": true,
    "full_sync_time": "23:23",
    "full_sync_on_startup": false
  },
  "logging": {
    "failure_log_file": "./logs/po-file-search-error.log"
  }
}
```

注意：

- `share` 是 SMB 共享文件夹名，不是子目录。
- 如果真实路径是 `\192.168.1.26\X.artwork2rtwork`，则：
  - `share = X.artwork2`
  - `relative_path = artwork`
- `download.base_url` 必须配置为用户能访问的 Linux 服务器 IP 或域名，不要用 `127.0.0.1`。

### 4. 设置群晖密码环境变量

如果配置里是：

```json
"password_env": "searchpassword"
```

则 Linux 上执行：

```bash
export searchpassword='你的群晖密码'
```

如果使用 systemd 部署，建议放到环境文件，例如：

```bash
sudo mkdir -p /etc/po-file-search
sudo tee /etc/po-file-search/env >/dev/null <<'EOF'
searchpassword=你的群晖密码
EOF
sudo chmod 600 /etc/po-file-search/env
```

### 5. 挂载群晖 SMB

#### 方式 A：程序执行挂载，适合测试

预览挂载命令：

```bash
python3 -m po_file_search --config config.json mount --dry-run
```

执行挂载通常需要 root 权限：

```bash
sudo -E python3 -m po_file_search --config config.json mount
```

`-E` 用于保留 `searchpassword` 环境变量。

#### 方式 B：系统负责挂载，推荐生产

生产环境更推荐用 `/etc/fstab` 或 systemd mount 先挂载群晖，然后程序只读访问挂载目录。

示例凭证文件：

```bash
sudo tee /etc/synology-credential >/dev/null <<'EOF'
username=cg-name_search
password=你的群晖密码
EOF
sudo chmod 600 /etc/synology-credential
```

手动测试挂载：

```bash
sudo mkdir -p /mnt/synology/purchase
sudo mount -t cifs //192.168.1.26/X.artwork2 /mnt/synology/purchase   -o credentials=/etc/synology-credential,ro,vers=3.0,iocharset=utf8
```

检查挂载：

```bash
mountpoint -q /mnt/synology/purchase && echo mounted
ls -la /mnt/synology/purchase
ls -la /mnt/synology/purchase/artwork
```

`/etc/fstab` 示例：

```text
//192.168.1.26/X.artwork2 /mnt/synology/purchase cifs credentials=/etc/synology-credential,ro,vers=3.0,iocharset=utf8,_netdev,nofail 0 0
```

加载 fstab：

```bash
sudo mount -a
```

### 6. 手动全量同步索引

首次部署后建议先手动全量同步一次：

```bash
python3 -m po_file_search --config config.json index
```

成功后输出类似：

```json
{"indexed": 92108}
```

### 7. 启动 HTTP 服务

前台启动：

```bash
python3 -m po_file_search --config config.json serve
```

后台启动：

```bash
nohup env searchpassword='你的群晖密码'   python3 -m po_file_search --config config.json serve   > /tmp/po-file-search-server.log 2>&1 &
```

健康检查：

```bash
curl http://Linux服务器IP或域名:18765/health
```

预期返回：

```json
{"ok": true}
```

### 8. 搜索测试

CLI 搜索：

```bash
python3 -m po_file_search --config config.json search 'DCC1039S.pdf' --mode exact --limit 0
```

HTTP 搜索：

```bash
curl -X POST http://Linux服务器IP或域名:18765/search_purchase_file   -H 'Content-Type: application/json'   -d '{"query":"DCC1039S.pdf","search_mode":"exact","limit":0}'
```

### 9. 生成下载链接测试

将 `file_id` 替换为搜索结果中的 ID：

```bash
curl -X POST http://Linux服务器IP或域名:18765/send_purchase_file   -H 'Content-Type: application/json'   -d '{"file_id":21559,"channel":"link","user_id":"linux-test"}'
```

然后用返回的 `download_url` 在浏览器中下载。

### 10. systemd 服务示例

创建服务文件：

```bash
sudo tee /etc/systemd/system/po-file-search.service >/dev/null <<'EOF'
[Unit]
Description=PO File Search Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/po-file-search
EnvironmentFile=/etc/po-file-search/env
ExecStart=/usr/bin/python3 -m po_file_search --config config.json serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable po-file-search
sudo systemctl start po-file-search
```

查看状态：

```bash
sudo systemctl status po-file-search
journalctl -u po-file-search -f
```

停止：

```bash
sudo systemctl stop po-file-search
```

### 11. Linux 部署常见问题

| 问题 | 可能原因 | 处理方式 |
|---|---|---|
| `mount: bad usage` 或找不到 cifs | 未安装 `cifs-utils` | 安装 `cifs-utils` |
| `Permission denied` | 挂载需要 root 权限 | 使用 `sudo -E` 或系统挂载 |
| 环境变量未设置 | `password_env` 指定的环境变量不存在 | `export searchpassword=...` 或 systemd `EnvironmentFile` |
| 下载链接打不开 | `download.base_url` 配成了 `127.0.0.1` 或防火墙未放行 | 改为服务器 IP/域名，开放端口 |
| 搜索不到新文件 | 本地索引未同步 | 手动执行 `python3 -m po_file_search --config config.json index` 或等待每日全量同步 |
| 容器内挂载失败 | Docker 默认无挂载权限 | 推荐宿主机挂载后 volume 只读映射 |

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

# 查看失败运行日志
tail -f logs/po-file-search-error.log

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

## 共享文件范围变更操作指南

当需要调整本服务允许搜索的群晖目录范围时，通常只需要修改 `config.json` 中的 `scan_roots`，不需要修改 `server` 和 `share`。

例如要从原范围：

```text
\\192.168.1.26\X.artwork2\artwork
```

变更为新范围：

```text
\\192.168.1.26\X.artwork2\1.包材印刷品\01-包装印刷品
```

对应关系是：

```text
server = 192.168.1.26
share = X.artwork2
relative_path = 1.包材印刷品/01-包装印刷品
```

注意：

- `share` 仍然是 SMB 共享文件夹名 `X.artwork2`。
- 子目录写到 `scan_roots[].relative_path`。
- Windows 路径中的 `\` 在 JSON 配置里建议写成 `/`。

### 推荐变更步骤

#### 1. 修改 config.json

把原配置：

```json
"scan_roots": [
  {
    "name": "采购共享/artwork",
    "path_from_mount": "采购共享",
    "relative_path": "artwork"
  }
]
```

改成：

```json
"scan_roots": [
  {
    "name": "采购共享/包装印刷品",
    "path_from_mount": "采购共享",
    "relative_path": "1.包材印刷品/01-包装印刷品"
  }
]
```

不要把 `share` 改成完整路径。下面这种写法是错误的：

```json
"share": "X.artwork2/1.包材印刷品/01-包装印刷品"
```

#### 2. 确认新目录存在

macOS：

```bash
ls -la "/Volumes/X.artwork2/1.包材印刷品/01-包装印刷品"
```

LinuxOS：

```bash
ls -la "/mnt/synology/purchase/1.包材印刷品/01-包装印刷品"
```

#### 3. 清空旧索引

因为 `scan_roots[].name` 从 `采购共享/artwork` 改成了 `采购共享/包装印刷品`，旧 `root_name` 下的索引不会被新同步自动清理。

为了保证索引范围干净，推荐直接删除旧索引库：

```bash
rm -f data/file_index.sqlite data/file_index.sqlite-*
```

#### 4. 重新全量同步索引

```bash
python3 -m po_file_search --config config.json index
```

成功后会输出类似：

```json
{"indexed": 12345}
```

#### 5. 重启服务

如果使用 systemd：

```bash
sudo systemctl restart po-file-search
```

如果手动后台运行：

```bash
pkill -f 'python3 -m po_file_search --config config.json serve'
nohup env searchpassword='你的群晖密码' \
  python3 -m po_file_search --config config.json serve \
  > /tmp/po-file-search-server.log 2>&1 &
```

#### 6. 验证服务和搜索

健康检查：

```bash
curl http://你的服务器IP或域名:18765/health
```

搜索验证：

```bash
python3 -m po_file_search --config config.json search '新目录中的文件关键词' --limit 10
```

HTTP 搜索验证：

```bash
curl -X POST http://你的服务器IP或域名:18765/search_purchase_file \
  -H 'Content-Type: application/json' \
  -d '{"query":"新目录中的文件关键词","limit":10}'
```

### Kimi Code 变更提示词

可以把下面提示词直接交给 Kimi Code：

```text
你是资深 Python/Linux 后端工程师。请在 po-file-search 项目中帮我完成共享文件搜索范围变更，并验证程序可用。

项目路径：
/Users/mac/workspace/po-file-search

当前群晖共享范围需要从：
\\192.168.1.26\X.artwork2\artwork

变更为：
\\192.168.1.26\X.artwork2\1.包材印刷品\01-包装印刷品

请注意：
1. server 仍然是 192.168.1.26。
2. share 仍然是 X.artwork2，不要改成完整路径。
3. 只修改 scan_roots 中的 name 和 relative_path。
4. relative_path 使用正斜杠：1.包材印刷品/01-包装印刷品。
5. 推荐配置：

"scan_roots": [
  {
    "name": "采购共享/包装印刷品",
    "path_from_mount": "采购共享",
    "relative_path": "1.包材印刷品/01-包装印刷品"
  }
]

请按以下步骤执行：

1. 修改 config.json 中的 scan_roots。
2. 不要修改 mounts[].server 和 mounts[].share。
3. 检查新目录是否存在：
   - macOS：ls -la "/Volumes/X.artwork2/1.包材印刷品/01-包装印刷品"
   - LinuxOS：ls -la "/mnt/synology/purchase/1.包材印刷品/01-包装印刷品"
4. 因为 root_name 变更了，请清空旧索引：
   rm -f data/file_index.sqlite data/file_index.sqlite-*
5. 重新全量同步索引：
   python3 -m po_file_search --config config.json index
6. 重启服务：
   如果是 systemd：sudo systemctl restart po-file-search
   如果是手动启动：先 pkill -f 'python3 -m po_file_search --config config.json serve'，再 nohup 启动。
7. 验证健康检查：
   curl http://服务器IP或域名:18765/health
8. 验证搜索：
   python3 -m po_file_search --config config.json search '新目录中的文件关键词' --limit 10
   或：
   curl -X POST http://服务器IP或域名:18765/search_purchase_file \
     -H 'Content-Type: application/json' \
     -d '{"query":"新目录中的文件关键词","limit":10}'
9. 如果出现错误，请查看失败日志：
   tail -100 logs/po-file-search-error.log

请输出：
1. 修改了哪些文件。
2. 最终 config.json 中 scan_roots 的内容。
3. 新目录是否存在。
4. 重新索引 indexed 数量。
5. 服务是否重启成功。
6. 搜索验证结果。
```

## 共享文件范围变更：macOS 与 LinuxOS 差异说明

本节补充实际变更共享范围时，macOS 和 LinuxOS 的操作差异。推荐在执行范围变更前先停止服务，避免 SQLite 索引库被运行中的服务进程占用。

### 通用变更流程

不论 macOS 还是 LinuxOS，推荐流程都是：

```text
1. 停止 po-file-search 服务
2. 确认新目录在挂载路径下可访问
3. 修改 config.json 的 scan_roots
4. 清空旧 SQLite 索引文件
5. 手动执行一次全量同步
6. 启动服务
7. 健康检查、搜索验证、下载验证
```

### 为什么要先停止服务

如果服务还在运行，可能持有旧的 SQLite 数据库文件。此时删除或重建索引，可能出现：

```text
sqlite3.OperationalError: attempt to write a readonly database
sqlite3.OperationalError: disk I/O error
```

因此变更范围前建议先停止服务。

### macOS 操作步骤

#### 1. 停止服务

如果是手动后台运行：

```bash
if [ -f /tmp/po-file-search-server.pid ]; then
  kill $(cat /tmp/po-file-search-server.pid) 2>/dev/null || true
fi
pkill -f 'python3 -m po_file_search --config config.json serve' || true
```

#### 2. 确认 Finder/SMB 挂载

macOS 推荐先在 Finder 里连接：

```text
smb://192.168.1.26/X.artwork2
```

程序会复用 Finder 挂载路径，例如：

```text
/Volumes/X.artwork2
```

检查新目录：

```bash
ls -la "/Volumes/X.artwork2/1.包材印刷品/01-包装印刷品"
```

如果刚调整过群晖权限但命令行看不到目录，请在 Finder 中断开 `X.artwork2` 后重新连接，再重试。

#### 3. 修改 config.json

```json
"scan_roots": [
  {
    "name": "采购共享/包装印刷品",
    "path_from_mount": "采购共享",
    "relative_path": "1.包材印刷品/01-包装印刷品"
  }
]
```

#### 4. 清空旧索引

macOS 默认 zsh 对不存在的通配符会报错，所以推荐用 Python 删除：

```bash
python3 - <<'PY'
from pathlib import Path
for p in Path('data').glob('file_index.sqlite*'):
    print('remove', p)
    p.unlink()
PY
```

不要使用不安全的通配符命令依赖，例如在 zsh 中直接执行：

```bash
rm -f data/file_index.sqlite data/file_index.sqlite-*
```

当通配符没有匹配时可能报错。

#### 5. 重新全量同步

```bash
/usr/bin/time -p env searchpassword='你的群晖密码' \
  python3 -m po_file_search --config config.json index
```

示例结果：

```text
{"indexed": 27471}
real 48.05
```

#### 6. 启动服务

```bash
nohup env searchpassword='你的群晖密码' \
  python3 -m po_file_search --config config.json serve \
  > /tmp/po-file-search-server.log 2>&1 &
echo $! > /tmp/po-file-search-server.pid
```

#### 7. 验证

健康检查：

```bash
curl http://192.168.88.20:18765/health
```

搜索验证：

```bash
python3 -m po_file_search --config config.json search 'Thumbs.db' --mode exact --limit 5
```

生成下载链接：

```bash
curl -X POST http://192.168.88.20:18765/send_purchase_file \
  -H 'Content-Type: application/json' \
  -d '{"file_id":8,"channel":"link","user_id":"scope-change-test"}'
```

下载验证：

```bash
curl -L -o /tmp/test-download.pdf '返回的 download_url'
file /tmp/test-download.pdf
```

### LinuxOS 操作步骤

LinuxOS 的核心区别是：通常不依赖 Finder，而是由系统或程序挂载 SMB 到 `mount_point_linux`。

#### 1. 停止服务

如果使用 systemd：

```bash
sudo systemctl stop po-file-search
```

如果手动后台运行：

```bash
pkill -f 'python3 -m po_file_search --config config.json serve' || true
```

#### 2. 确认 SMB 已挂载

假设 Linux 挂载点为：

```text
/mnt/synology/purchase
```

检查挂载：

```bash
mountpoint -q /mnt/synology/purchase && echo mounted
```

如果未挂载，可用系统挂载或程序挂载：

```bash
sudo -E python3 -m po_file_search --config config.json mount
```

#### 3. 确认新目录存在

```bash
ls -la "/mnt/synology/purchase/1.包材印刷品/01-包装印刷品"
```

如果目录不存在，请检查：

- 群晖权限是否给到 Linux 使用的账号。
- `mounts[].share` 是否仍为 `X.artwork2`。
- `relative_path` 是否写错。
- Linux 是否挂载了正确的群晖共享。

#### 4. 修改 config.json

同 macOS：

```json
"scan_roots": [
  {
    "name": "采购共享/包装印刷品",
    "path_from_mount": "采购共享",
    "relative_path": "1.包材印刷品/01-包装印刷品"
  }
]
```

#### 5. 清空旧索引

Linux bash 下可以执行：

```bash
rm -f data/file_index.sqlite data/file_index.sqlite-*
```

也可以使用跨平台 Python 方式：

```bash
python3 - <<'PY'
from pathlib import Path
for p in Path('data').glob('file_index.sqlite*'):
    print('remove', p)
    p.unlink()
PY
```

#### 6. 重新全量同步

```bash
/usr/bin/time -p env searchpassword='你的群晖密码' \
  python3 -m po_file_search --config config.json index
```

#### 7. 启动服务

systemd：

```bash
sudo systemctl start po-file-search
```

或手动：

```bash
nohup env searchpassword='你的群晖密码' \
  python3 -m po_file_search --config config.json serve \
  > /tmp/po-file-search-server.log 2>&1 &
```

#### 8. 验证

健康检查：

```bash
curl http://Linux服务器IP或域名:18765/health
```

搜索验证：

```bash
curl -X POST http://Linux服务器IP或域名:18765/search_purchase_file \
  -H 'Content-Type: application/json' \
  -d '{"query":"新目录中的文件关键词","limit":10}'
```

生成下载链接验证：

```bash
curl -X POST http://Linux服务器IP或域名:18765/send_purchase_file \
  -H 'Content-Type: application/json' \
  -d '{"file_id":实际文件ID,"channel":"link","user_id":"scope-change-test"}'
```

### 本次实际变更结果示例

本次从：

```text
\\192.168.1.26\X.artwork2\artwork
```

变更为：

```text
\\192.168.1.26\X.artwork2\1.包材印刷品\01-包装印刷品
```

最终配置：

```json
"scan_roots": [
  {
    "name": "采购共享/包装印刷品",
    "path_from_mount": "采购共享",
    "relative_path": "1.包材印刷品/01-包装印刷品"
  }
]
```

重新索引结果：

```text
indexed: 27471
耗时: 约 48 秒
```

服务验证：

```json
{"ok": true}
```

下载链路验证：

```text
HTTP/1.0 200 OK
Content-Type: application/pdf
```
