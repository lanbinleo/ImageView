# ImageRating API 契约

前后端唯一契约。改动接口必须先改本文件。实现见 `app/main.py`。

## 通用约定

- 所有 `/api/*` 返回 JSON；错误用 HTTP 状态码 + `{"detail": "中文错误信息"}`。
- 除 `login` / `logout` / `setup` / `session` 外，全部接口要求会话 Cookie，未登录返回 **401** `{"detail":"未登录"}`。
- Cookie 名 `ir_sess`：HttpOnly、SameSite=Lax、Path=/、Max-Age 30 天，值为服务端 HMAC 签名的过期时间戳。
- 时间字段统一为 **Unix 秒（float）**，前端自行格式化。
- `mtime` 用作图片缓存版本号，URL 里带 `?v=<int(mtime)>`。

## 数据对象

### Image

```json
{
  "id": 12,
  "filename": "ComfyUI_00001_.png",
  "rel_path": "2026-10-31/ComfyUI_00001_.png",
  "size": 1234567,
  "mtime": 1761926400.0,
  "width": 1024,
  "height": 1024,
  "score": 4,
  "loved": true,
  "trashed": false,
  "organized": false,
  "missing": false,
  "orig_rel_path": null,
  "rated_at": 1761926500.0,
  "collections": [{"id": 1, "name": "精选"}],
  "thumb_url": "/api/img/thumb/12?v=1761926400",
  "full_url": "/api/img/full/12?v=1761926400"
}
```

- `score`：`null` = 未评分，`0` = 有明显瑕疵作废，`1..5` = 星级。
- `loved`：独立收藏标记，与 Collection 无关。
- `trashed`：Trash 是内置集合，用布尔字段表示。
- `organized`：文件已被移入 `<root>/_trash/`。
- `missing`：文件已不在磁盘上（默认从列表排除）。
- `collections`：该图所属的用户 Collection。

### Collection

```json
{"id": 1, "name": "精选", "count": 23, "created_at": 1761926000.0}
```

`count` 只统计未缺失的图片。

### Stats

```json
{
  "total": 340,
  "unrated": 120,
  "loved": 12,
  "trash": 8,
  "scores": {"0": 8, "1": 3, "2": 9, "3": 40, "4": 60, "5": 20}
}
```

- 都只统计 `missing = 0` 的图片。
- `scores` 只统计**未进 Trash** 的图。因为 `rate 0` 一定进 Trash，`scores["0"]` 恒为 0；作废图数量看 `trash`。
- `view=all` 也包含 `trashed = true` 的图，只是默认排除 `missing = 1`。

## 认证

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/session` | – | `{"authed": bool, "needs_setup": bool}` |
| POST | `/api/setup` | `{"password": "..."}` | `{"ok": true}`；密码 < 4 字符 400；已设置过密码 409 |
| POST | `/api/login` | `{"password": "..."}` | `{"ok": true}`；密码错误 401；尚未设置密码 400 |
| POST | `/api/logout` | – | `{"ok": true}`，清除 Cookie |

- `needs_setup = true` 表示数据库里还没有密码：前端登录页切换为「设置密码」表单。
- `setup` 成功即视为登录。

## 图片列表

`GET /api/images`

| 参数 | 说明 |
|---|---|
| `view` | `all`(默认) / `unrated` / `score` / `loved` / `trash` / `collection` |
| `score` | 当 `view=score`，取值 0–5 |
| `collection` | 当 `view=collection`，Collection id |
| `q` | 文件名子串搜索（不区分大小写） |
| `sort` | `newest`(默认) / `oldest` / `score_high` / `score_low` / `random`；`random` 每次请求独立随机，翻页可能重复或漏图 |
| `page` | 1 起，默认 1 |
| `per_page` | 默认 60，最大 200 |

响应：

```json
{"items": [Image, ...], "total": 340, "page": 1, "last_page": 6,
 "stats": Stats, "collections": [Collection, ...]}
```

- `total` / `last_page` 对应**当前筛选**的结果数；`stats`、`collections` 是全局数据。
- 默认排除 `missing = 1`。
- `view=unrated`：`score IS NULL AND trashed = 0`。
- `view=score`：`score = N`，且 `trashed = 0`（`score=0` 的图在 Trash 里，用 `view=trash` 看）。
- `view=trash`：`trashed = 1`（含已整理到 `_trash/` 的图）。
- `view=loved`：`loved = 1`（不排除 Trash 中的图）。
- `view=collection`：属于该 Collection 的图（不排除 Trash 中的图）。

`GET /api/images/{id}` → 单个 Image；不存在 404。

## 单张操作

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/images/{id}/rate` | `{"score": 0..5}` 或 `{"score": null}` | `{"item": Image}` |
| POST | `/api/images/{id}/loved` | `{"loved": bool}` | `{"item": Image}` |
| POST | `/api/images/{id}/trash` | `{"trashed": bool}` | `{"item": Image}` |

`rate` 的联动规则（固定行为，前端不要重复实现）：

- `score = 0` → 同时 `trashed = true`。
- `score = 1..5` → 同时 `trashed = false`。
- `score = null` → 只清空分数，`trashed` 不变。

## 批量操作

`POST /api/images/batch`

```json
{"ids": [1, 2, 3], "op": "rate | loved | trash", "score": 4, "loved": true, "trashed": true}
```

- `op=rate` 用 `score`，`op=loved` 用 `loved`，`op=trash` 用 `trashed`；联动规则同上。
- 响应 `{"updated": 3}`；不存在的 id 静默忽略。
- 属于 Trash 的图批量打 1–5 分会被移出 Trash（与单张一致）。

### 撤回专用：精确状态回填

```json
{"op": "state", "items": [
  {"id": 1, "score": null, "trashed": false},
  {"id": 2, "loved": true}
]}
```

- 只更新 `items[i]` 中**显式给出**的字段（字段缺省＝不动，显式 `null`＝清空）；不走 `rate` 的 Trash 联动规则，用于前端 Ctrl+Z 把图恢复成操作前的精确状态。
- 可用字段：`score`（0–5 或 null）、`trashed`（bool）、`loved`（bool）、`rated_at`（Unix 秒或 null）。
- 响应 `{"updated": 2}`；不存在的 id 静默忽略；`score` 超出 0–5 返回 400。

## Collections

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/collections` | – | `[Collection, ...]`（按创建时间） |
| POST | `/api/collections` | `{"name": "精选"}` | `Collection`；重名 409；空名 400 |
| PATCH | `/api/collections/{id}` | `{"name": "新名字"}` | `Collection`；重名 409 |
| DELETE | `/api/collections/{id}` | – | `{"ok": true}`（只删集合与成员关系，不动图片） |
| POST | `/api/collections/{id}/images` | `{"ids": [...], "action": "add" \| "remove"}` | `{"count": 23}`（集合当前图片数） |

- 名字长度 1–50，首尾空白去掉。
- 一张图可属于多个 Collection。
- `ids` 必须是已存在的图片 id；`DELETE /api/collections/{id}` 对不存在的 id 也返回 `{"ok": true}`（幂等）。

## 扫描

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/scan` | – | `{"running": true, "status": ScanStatus}` |
| GET | `/api/scan/status` | – | `ScanStatus` |

```json
{"running": false, "total": 340, "done": 340, "added": 5, "updated": 2,
 "missing": 1, "errors": 0, "started_at": 1761926000.0, "ended_at": 1761926012.0,
 "error": null}
```

扫描规则（后端实现，前端只展示）：

- 递归遍历 `<root>`；跳过 `.` 开头的目录、`_trash` 目录、`data_dir`。
- 支持的扩展名：`.png .jpg .jpeg .webp .gif .bmp`（忽略大小写）。
- 已存在且 `size`、`mtime` 都没变的文件跳过；新文件插入；变化的更新尺寸信息。
- 本次未见到的行标记 `missing = 1`；重新出现的行恢复 `missing = 0`。`rel_path` 以 `_trash/` 开头的行不参与 missing 标记。
- 扫描在后台线程运行，同一时间只允许一个扫描任务。

## 物理整理 / 恢复

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/organize` | `{"ids": [...]}` | `{"moved": 3, "failed": [{"id": 9, "reason": "不在 Trash 中"}]}` |
| POST | `/api/restore` | `{"ids": [...]}` | 同上结构 |

- `organize`：只处理 `trashed = 1 AND organized = 0 AND missing = 0` 的图，把文件移到 `<root>/_trash/<filename>`；重名时加 `_1`、`_2` 后缀。成功后 `rel_path` 变为 `_trash/...`、`orig_rel_path` 记录原路径、`organized = true`、`size/mtime` 保持不变。
- `restore`：只处理 `organized = true` 且文件在 `_trash/` 中的图，移回 `orig_rel_path`，清空 `orig_rel_path`、`organized = false`、`trashed = false`；原路径已被磁盘文件或数据库其他记录占用则失败，原目录不存在时会自动重建。
- 两者都不删除任何文件。

## 图片内容

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/img/thumb/{id}?v=` | 512px 最长边 WebP 缩略图，缓存到 `data/thumbs/<id>-<mtime>.webp`；`Cache-Control: private, max-age=31536000, immutable` |
| GET | `/api/img/full/{id}?v=` | 原图字节流，`Content-Type` 按扩展名；同上缓存头 |

- 文件缺失返回 404 `{"detail":"文件不存在"}`。
- 动态 GIF / 动态 WebP 取第一帧做缩略图；带透明通道的图保留 alpha。

## 设置

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/settings` | – | `{"version": "0.2.1", "root": "D:/ComfyUI/output", "host": "0.0.0.0", "port": 17900, "data_dir": "D:/Desktop/ImageRating/data"}` |
| PUT | `/api/settings` | `{"root": "...", "current_password": "...", "new_password": "..."}` 均可选 | `{"ok": true, "scan_started": bool}` |

- `root` 必须存在且是目录，否则 400；改变 root 后自动触发重扫描，`scan_started = true`（若已有扫描在跑则为 `false`）。
- 提供 `new_password` 时必须同时提供正确的 `current_password`，否则 **400**（不能用 401，前端会把 401 当成会话失效而踢回登录页）；改密码后当前会话保持有效。

## 测试钩子

- 应用工厂：`from app.main import create_app`，`create_app(data_dir: str | None = None)`。传 `data_dir` 时数据库与缩略图缓存都写在该目录下，测试用临时目录，绝不碰仓库里的 `data/`。
- 启动入口：`uv run python -m app`（读 `config.json`，读不到默认 `0.0.0.0:17900`、`data_dir="data"`）。
- 测试用 `fastapi.testclient.TestClient(create_app(data_dir=tmp))`；图片根目录通过 `PUT /api/settings` 设置。
- 测试不需要真实密码：`POST /api/setup` 设一个即可。

## 静态文件

| 路径 | 内容 |
|---|---|
| `GET /` | `web/index.html` |
| `GET /app.css` `/app.js` `/theme.js` | `web/` 下同名文件，`Cache-Control: no-cache` |
| `GET /favicon.ico` | 固定返回 204（无图标） |

前端不得请求本契约之外的接口；需要新接口时先改本文件。
