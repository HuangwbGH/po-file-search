# DatabaseSchema：采购文件搜索服务

## 目录

- [概述](#概述)
- [数据库文件](#数据库文件)
- [表清单](#表清单)
- [files 表](#files-表)
- [files_fts 虚拟表](#files_fts-虚拟表)
- [触发器](#触发器)
- [audit_logs 表](#audit_logs-表)
- [download_tokens 表](#download_tokens-表)
- [字段影响范围](#字段影响范围)
- [后续表设计](#后续表设计)

## 概述

本项目 MVP 使用 SQLite 作为 OpenClaw 服务器本地文件索引库。搜索请求查询本地 SQLite/FTS 索引，不依赖群晖搜索能力。

当前数据库保存：

- 文件元数据。
- FTS 搜索索引。
- 基础审计日志。
- 下载 token。

当前数据库不保存文件正文，也不保存文件内容。

## 数据库文件

默认路径：

```text
./data/file_index.sqlite
```

该路径可通过 `config.json` 的 `index_db` 配置修改。

## 表清单

| 表/对象 | 类型 | 说明 |
|---|---|---|
| `files` | 普通表 | 文件元数据主表 |
| `files_fts` | FTS5 虚拟表 | 文件名、文件夹路径的全文索引 |
| `files_ai` | 触发器 | `files` 插入后同步写入 FTS |
| `files_ad` | 触发器 | `files` 删除后同步删除 FTS |
| `files_au` | 触发器 | `files` 更新后同步更新 FTS |
| `audit_logs` | 普通表 | 搜索、发送、下载审计日志 |
| `download_tokens` | 普通表 | 下载链接 token |

## files 表

建表逻辑位于：

```text
po_file_search/indexer.py
```

表结构：

```sql
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
```

字段说明：

| 字段 | 类型 | 是否必填 | 含义 | 影响范围 |
|---|---|---:|---|---|
| `id` | INTEGER | 是 | 本地文件记录主键 | 作为 `file_id` 返回给 OpenClaw 和发送工具使用 |
| `root_name` | TEXT | 是 | 文件所属扫描根目录名称 | 区分多个共享目录或业务目录 |
| `file_name` | TEXT | 是 | 文件名，不含父级路径 | 搜索、结果展示、发送确认 |
| `folder_path` | TEXT | 是 | 相对扫描根目录的文件夹路径 | 搜索、结果展示、权限和目录判断辅助 |
| `full_path` | TEXT | 是 | OpenClaw 服务器上的真实挂载路径 | 发送阶段读取文件；不应直接暴露给普通用户 |
| `extension` | TEXT | 是 | 文件扩展名，小写且不含点 | 后续支持按文件类型筛选 |
| `size` | INTEGER | 是 | 文件大小，单位字节 | 结果展示、发送限制判断 |
| `modified_time` | REAL | 是 | 文件修改时间，Unix timestamp | 结果排序、变更判断 |

### 写入规则

- 新文件：插入 `files`。
- 已存在文件：按 `full_path` 冲突更新元数据。
- 读取失败的文件：跳过。
- 隐藏文件：跳过。
- 忽略目录：由 `config.json` 的 `ignored_dirs` 控制。

### 删除清理

索引任务会记录本轮扫描看到的 `full_path`。扫描结束后，同一 `root_name` 下没有再次出现的旧记录会从 `files` 删除，并通过触发器同步清理 `files_fts`。

## files_fts 虚拟表

表结构：

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_name,
    folder_path,
    full_path UNINDEXED,
    content='files',
    content_rowid='id'
);
```

字段说明：

| 字段 | 类型 | 是否索引 | 含义 | 影响范围 |
|---|---|---:|---|---|
| `file_name` | TEXT | 是 | 文件名全文索引 | 智能搜索 |
| `folder_path` | TEXT | 是 | 文件夹路径全文索引 | 按目录名智能搜索 |
| `full_path` | TEXT | 否 | 完整路径，仅随结果返回内部使用 | 发送阶段定位文件 |

说明：

- `files_fts` 使用 `files` 作为内容表。
- `content_rowid='id'` 表示 FTS 记录与 `files.id` 对应。
- `full_path UNINDEXED` 表示不对完整路径做全文索引。
- `smart` 模式会优先使用 FTS 搜索。
- `left_contains`、`right_contains`、`contains`、`exact` 使用 `files` 表上的 LIKE 或等值匹配。

## 触发器

### files_ai

`files` 插入后，同步插入 `files_fts`。

影响：保证新增文件可以被 FTS 搜索到。

### files_ad

`files` 删除后，同步删除 `files_fts`。

影响：保证已删除文件不会继续出现在 FTS 搜索中。

### files_au

`files` 更新后，先删除旧 FTS 记录，再写入新 FTS 记录。

影响：保证文件重命名、移动或修改元数据后，搜索结果同步更新。

## audit_logs 表

表结构：

```sql
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
```

字段说明：

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | INTEGER | 审计记录 ID |
| `event_type` | TEXT | `search`、`send`、`download` 等 |
| `user_id` | TEXT | 操作用户 |
| `query` | TEXT | 搜索关键词 |
| `file_id` | INTEGER | 关联文件 ID |
| `recipient` | TEXT | 接收人或群 ID |
| `channel` | TEXT | `link`、`dingtalk` 等 |
| `created_at` | REAL | 事件时间，Unix timestamp |
| `metadata` | TEXT | JSON 扩展字段 |

## download_tokens 表

表结构：

```sql
CREATE TABLE IF NOT EXISTS download_tokens (
    token TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL,
    user_id TEXT,
    expire_at REAL NOT NULL,
    used_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY(file_id) REFERENCES files(id)
);
```

字段说明：

| 字段 | 类型 | 含义 |
|---|---|---|
| `token` | TEXT | 下载 token |
| `file_id` | INTEGER | 文件 ID |
| `user_id` | TEXT | 授权下载用户，当前主要用于审计 |
| `expire_at` | REAL | 过期时间；大于 0 表示 Unix timestamp，等于 0 表示永不过期 |
| `used_at` | REAL | 首次下载时间 |
| `created_at` | REAL | 创建时间 |

下载校验规则：

- token 不存在：拒绝下载。
- `expire_at > 0` 且当前时间大于 `expire_at`：拒绝下载。
- `expire_at = 0`：不做时间过期校验。
- 文件不存在：拒绝下载。

## 字段影响范围

| 字段 | 搜索阶段 | 发送阶段 | 审计阶段 | 用户展示 |
|---|---:|---:|---:|---:|
| `id` | 是 | 是 | 是 | 可作为 `file_id` |
| `root_name` | 是 | 是 | 是 | 是 |
| `file_name` | 是 | 是 | 是 | 是 |
| `folder_path` | 是 | 是 | 是 | 是 |
| `full_path` | 否 | 是 | 是 | 否 |
| `extension` | 可选 | 可选 | 可选 | 是 |
| `size` | 否 | 可选 | 可选 | 是 |
| `modified_time` | 排序 | 可选 | 可选 | 是 |

## 后续表设计

后续接入企业级权限后，建议增加用户、角色、目录授权等表。

### permissions

建议字段：

| 字段 | 含义 |
|---|---|
| `id` | 授权记录 ID |
| `principal_type` | 用户、部门、角色 |
| `principal_id` | 用户、部门或角色 ID |
| `root_name` | 授权根目录 |
| `folder_prefix` | 授权目录前缀 |
| `created_at` | 创建时间 |


## 索引同步配置说明

索引同步配置不存储在 SQLite 中，而是存储在 `config.json`：

```json
"index": {
  "sync_interval_minutes": 60,
  "sync_on_startup": false
}
```

同步任务会更新 `files` 和 `files_fts`，并清理已经不存在的旧文件记录。

| 配置项 | 含义 |
|---|---|
| `sync_interval_minutes > 0` | 服务运行期间每 N 分钟自动同步一次索引 |
| `sync_interval_minutes = 0` | 关闭自动同步 |
| `sync_on_startup = true` | 服务启动后立即同步一次 |
| `sync_on_startup = false` | 服务启动后等待下一个同步周期 |

## 当前同步策略说明

当前暂行方案删除后台增量同步，只保留：

- 每天指定时间全量同步一次，默认 `23:23`。
- 管理员手动全量同步。

同步配置不存储在 SQLite 中，而是存储在 `config.json`：

```json
"index": {
  "auto_full_sync_enabled": true,
  "full_sync_time": "23:23",
  "full_sync_on_startup": false
}
```

全量同步会更新 `files` 和 `files_fts`，并清理已经不存在的旧文件记录。

历史版本曾实验目录级增量同步，但实测瓶颈主要是 SMB 目录遍历，无变化增量同步耗时仍接近全量同步，因此暂不保留后台增量同步。
