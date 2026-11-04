# ImageRating 架构说明

本文面向维护者，说明系统由哪些部分组成、状态存在哪里，以及关键规则为什么这样设计。
部署与运维见 [DEPLOYMENT.md](DEPLOYMENT.md)，接口契约见 [API.md](API.md)，开发流程见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 1. 定位与设计约束

- **本地单用户 Web 应用**：跑在 ComfyUI 主机上，浏览器通过局域网访问，不面向公网。
- **元数据与文件分离**：评分、收藏、Collection、密码、图库根目录全部存 SQLite；图片文件只在「物理整理 / 恢复」时移动，任何操作都不删除文件。
- **零构建前端**：`web/` 下是原生 HTML / CSS / JS，无框架、无打包器、无 CDN，断网可用。
- **单进程部署**：uvicorn 一个 worker，扫描用进程内后台线程，不引入 Redis、任务队列等外部服务。

## 2. 运行拓扑

```
┌──────────────── 浏览器（桌面 / 手机） ────────────────┐
│  web/index.html + app.js + app.css + theme.js          │
└───────────────┬────────────────────────────────────────┘
                │ HTTP，会话 Cookie `ir_sess`
┌───────────────▼────────────────────────────────────────┐
│ FastAPI 应用（uvicorn，单进程）                         │
│   app/main.py       路由 / 鉴权依赖 / 静态文件          │
│   app/auth.py       密码哈希 / 会话 Cookie 签名        │
│   app/db.py         SQLite 表结构、查询、序列化         │
│   app/scan.py       目录扫描 / 缩略图 / 物理整理        │
│   app/settings.py   读取 config.json                    │
└──────┬──────────────────────────────┬──────────────────┘
       │                              │
┌──────▼──────────────┐      ┌────────▼─────────────────────┐
│ data/rating.db      │      │ <图片根目录>（ComfyUI 输出） │
│ data/thumbs/        │      │   └─ _trash/（整理后）       │
└─────────────────────┘      └──────────────────────────────┘
```

一次页面访问的路径：

1. 浏览器请求 `/`，后端返回 `web/index.html`；页面再加载 `/app.css`、`/app.js`、`/theme.js`。
2. 前端用 `GET /api/session` 判断登录状态；未登录显示密码页。
3. 登录后通过 `/api/*` 读写评分与分组数据；列表接口同时返回全局统计。
4. 图片内容通过 `/api/img/thumb/{id}`、`/api/img/full/{id}` 按需读取并缓存缩略图。
5. 扫描在后台线程执行，前端轮询 `/api/scan/status` 显示进度。

## 3. 模块职责

| 模块 | 职责 | 关键点 |
|---|---|---|
| `app/settings.py` | 读 `config.json`，定位项目根目录与 `web/` | 只有 `host` / `port` / `data_dir`；`IR_CONFIG` 环境变量可指向另一份配置 |
| `app/auth.py` | PBKDF2-SHA256 密码哈希、HMAC 会话签名与校验 | 无服务端会话存储；Cookie 值即「过期时间 + 签名」 |
| `app/db.py` | 建表、连接、筛选/排序/分页、统计、序列化 | `rated_score_fields()` 是评分→Trash 联动的唯一实现；`to_item()` 负责行转 JSON |
| `app/main.py` | `create_app()` 工厂、全部路由、鉴权依赖、扫描线程、静态文件 | 测试与脚本只能用工厂，不能 import 模块级 app |
| `app/scan.py` | 递归扫描、缩略图、物理整理 / 恢复 | 唯一允许移动图片文件的代码 |
| `web/index.html` | 页面骨架：登录、顶栏、侧栏、Ranking、Grid、灯箱、抽屉、弹窗 | 全部界面元素在这里声明一次 |
| `web/app.js` | 状态、渲染、事件、API 调用、撤回栈 | 按 `---------- Ranking ----------` 等注释分段 |
| `web/app.css` | 主题变量、布局、响应式（760px 断点）、组件样式 | 深/浅色由 CSS 变量切换 |
| `web/theme.js` | 首帧前读取 `localStorage.theme` 写入 `data-theme` | 避免主题闪烁，必须同步执行 |
| `tests/test_api.py` | HTTP 层集成测试，按 `docs/API.md` 断言 | 每个用例独立临时 `data_dir` 与图片根目录 |
| `tests/make_samples.py` | 生成合成样图（含瑕疵图） | 测试夹具与人工验证共用 |

## 4. 数据模型

SQLite 数据库默认位于 `data/rating.db`（`data_dir` 可配置），启用 WAL 模式。

### 4.1 表

```sql
images(id, rel_path UNIQUE, filename, size, mtime, width, height,
       score, loved, trashed, missing, orig_rel_path, rated_at, created_at)
collections(id, name UNIQUE, created_at)
collection_images(collection_id, image_id)   -- 主键 (collection_id, image_id)
settings(key, value)
```

- `images` 一行对应磁盘上一张图；`rel_path` 是相对图片根目录的 POSIX 路径，唯一。
- `collections` 是用户创建的 Collection；**Trash 不是表里的一行**，而是 `images.trashed` 布尔字段。
- `collection_images` 多对多，删除 Collection 时靠外键 `ON DELETE CASCADE` 清理成员关系。
- `settings` 是键值表，当前使用的 key：

| key | 内容 | 写入时机 |
|---|---|---|
| `root` | 图片根目录绝对路径 | 首次 / 设置页保存 |
| `password_hash` | `pbkdf2_sha256$轮数$盐$摘要` | 首次设置密码 / 修改密码 |
| `secret` | 会话签名密钥（32 字节 hex） | 首次启动随机生成 |

### 4.2 派生字段与不变式

`organized` 不是数据库列，由 `rel_path` 是否以 `_trash/` 开头派生；`thumb_url` / `full_url` 也由 `id` + `mtime` 生成。

必须保持的规则（改代码不得破坏，测试已覆盖）：

1. `score = 0` → `trashed = 1`；`score = 1..5` → `trashed = 0`；`score = null` 只清空分数，不改 Trash 状态。这条联动只在后端实现。
2. `loved` 与 Collection 无关，是独立布尔标记。
3. `missing = 1` 的图默认不出现在列表与统计里；扫描重新看到文件时恢复为 0。
4. `rel_path` 以 `_trash/` 开头的行不参与 missing 标记 —— 物理整理后 `_trash/` 目录本身不会被扫描，否则每次扫描都会把已整理的图标成缺失。
5. Trash 包含已物理整理的图（`trashed = 1` 即可），所以整理不会让图从 Trash 视图消失。
6. Collection 的 `count` 只统计未缺失的图片；成员关系本身不受 Trash 影响。
7. 数据库是唯一真相：即使图片被 ComfyUI 或用户移动，记录也保留，靠重新扫描标记缺失或恢复。

### 4.3 表结构演进

当前没有迁移框架：`init_db()` 只执行 `CREATE TABLE IF NOT EXISTS`。已有数据库上的新增列 / 索引必须通过兼容的 `ALTER TABLE` / 回填逻辑完成，并在发版说明中写清；不要假设用户会删库重建。

## 5. 鉴权与会话

```
设置密码（仅首次）           登录
POST /api/setup  ──┐   ┌── POST /api/login
                   ▼   ▼
        password_hash ← PBKDF2-SHA256（20 万轮 + 随机盐）
                   │
                   ▼
        签名 Cookie：<expires>.<HMAC-SHA256(secret, expires)>
```

- Cookie `ir_sess`：`HttpOnly`、`SameSite=Lax`、`Path=/`、30 天；没有服务端会话表。
- 所有数据接口都通过 `require_auth` 依赖校验；只有 `session` / `setup` / `login` / `logout` 公开。
- 修改密码只改哈希，**不会让已签发的 Cookie 失效**（签名密钥没变）。需要强制所有设备重新登录时，删除 `settings.secret`，重启后会自动生成新密钥。
- CSRF：依赖 `SameSite=Lax` + 同源 JSON 请求，未额外引入 token；这符合「可信局域网、单用户」的假设，不代表适合公网。
- 文件访问只能通过数据库中的 `rel_path` 拼接图片根目录，客户端无法传入任意路径；静态文件也是固定白名单。

## 6. 扫描与缩略图

**触发**：`POST /api/scan`，或修改图库根目录后自动触发。`app.state.scan` 保存进度，`scan_lock` 保证同一时刻只有一个扫描任务。

**遍历规则**（`scan._walk`）：

- 递归遍历图片根目录；
- 跳过 `.` 开头的目录、`_trash` 目录、以及 `data_dir`（避免把数据库和缩略图当图片）；
- 只收 `.png .jpg .jpeg .webp .gif .bmp`（不区分大小写）；
- 结果按路径排序，保证扫描顺序稳定。

**增量逻辑**（逐文件）：

| 情况 | 行为 |
|---|---|
| 数据库没有该 `rel_path` | 读取宽高后插入，`added + 1` |
| 行存在，size / mtime 未变，且未标记缺失 | 跳过 |
| 行存在，size 或 mtime 变化，或之前缺失 | 更新文件信息并恢复 `missing = 0`，`updated + 1` |
| 本次没见到的历史行 | 标记 `missing = 1`（`_trash/%` 行除外） |

每个文件扫描后提交一次事务，扫描期间前端仍可读写。单个文件 `OSError` 计入 `errors`，不中断整体扫描；扫描级异常写入状态里的 `error` 并结束任务。

**缩略图**：首次请求时生成，最长边 512 的 WebP（质量 82），缓存到 `data/thumbs/<id>-<mtime>.webp`。URL 带 `?v=<int(mtime)>`，配合一年期 immutable 缓存头。文件变化后 mtime 变，URL 变，自然产生新缓存；旧缩略图不会自动清理，可安全删除 `data/thumbs/` 让其重建。

## 7. 物理整理与恢复

这是唯一会移动图片文件的两条路径，且都**只移动、不删除**：

**整理**（`POST /api/organize`）：

1. 只处理 `trashed = 1 AND missing = 0 AND rel_path 不以 _trash/ 开头` 的图；
2. 目标目录 `<root>/_trash/`；与磁盘或数据库重名时依次加 `_1`、`_2` 后缀；
3. `shutil.move` 后更新 `rel_path`、`filename`，并把原路径写入 `orig_rel_path`；
4. `size` / `mtime` 保持不变；逐张提交，失败只记入响应的 `failed`，不回滚其他成功项。

**恢复**（`POST /api/restore`）：

1. 只处理 `rel_path` 以 `_trash/` 开头且有 `orig_rel_path` 的图；
2. 原位置被磁盘文件或数据库其他行占用则失败；原目录不存在时会自动重建；
3. 移回后清空 `orig_rel_path`，设置 `trashed = 0`、`missing = 0`。

整理 / 恢复不进入 `Ctrl+Z` 撤回栈 —— 它们的逆操作是「恢复」，语义上比撤回更明确。手动清理 `_trash/` 目录前要注意：数据库记录不会自动删除，图会变成打不开的整理状态；想清理请先在应用里确认不再需要这些记录。

## 8. 前端架构

`web/` 是单页应用，但没有任何构建步骤，浏览器直接执行源码。

**状态**：`app.js` 顶部的 `state` 是唯一状态源，包含当前筛选、排序、搜索词、视图模式（`ranking` / `grid`）、统计、Collection 列表、两套分页列表（`rank` / `grid`）、选中集合、详情抽屉和灯箱状态。

**渲染**：没有虚拟 DOM，按视图整块重建或按 id 局部替换。Grid 每页 60 张，用 `IntersectionObserver` 触底加载；Ranking 自己维护分页与预加载。

**数据流**：

- `api()` 统一封装 `fetch`；收到 401 时回到登录页。
- 单张操作（打分 / 收藏 / Trash）与批量操作走 `docs/API.md` 定义的接口；响应里的最新 item 覆盖本地缓存。
- 统计与 Collection 计数在列表响应里整体刷新（`applyMeta`）。
- 撤回栈只存在内存里（上限 50 条），刷新页面即丢；它只记录 Meta 操作，回填走 `POST /api/images/batch {op:"state"}` 的精确字段更新，不触发评分→Trash 联动。

**弹层**：详情抽屉、设置、快捷键、命名框都是 `<dialog>`；灯箱是叠在抽屉之上的 `<dialog id="lightbox">`。全局快捷键遇到「有打开的非灯箱 dialog」才禁用 —— 灯箱内必须继续响应打分与切图。CSS 规则必须保持「基础 `display: none`，仅 `[open]` 时 `display: flex`」，否则关闭状态会被作者样式强行显示成透明遮罩（v0.2.1 修过）。

**主题与本地持久化**：`theme.js` 在首帧前同步执行，避免闪烁；主题、筛选、排序分别存在 `localStorage` 的 `theme`、`ir.filter`、`ir.sort`。

**手机版**：断点 760px。侧栏折叠成筛选条、Grid 两列、抽屉全屏、灯箱与按钮适配触屏；验证视口 390×844。没有单独的手机页面，桌面与手机共用同一套 DOM 与代码。

## 9. 并发与一致性

- SQLite 单写者：连接按请求创建，`WAL` + `busy_timeout = 30000` 兜住读写并发；关闭连接由依赖的 `finally` 保证。
- 扫描线程使用自己的连接；每处理一个文件提交一次，避免长时间持锁阻塞前端操作。
- 没有跨请求事务，也没有分布式锁；所有「检查 + 写入」以单次请求内的 SQL 语句为准。
- `app.state.scan` 是进程内字典；**只支持单 worker / 单实例**。`uvicorn --workers 2` 或同时启动两个服务指向同一 `data_dir` 会导致进度状态不一致、并发扫描和写锁竞争。
- 整理 / 恢复的「检查 + 移动」不是原子操作；失败只影响当前这张图，并在响应 `failed` 中说明。

## 10. 安全模型

- 假设：可信局域网、单用户、浏览器与服务在同一信任边界内。
- 传输是 HTTP 明文，密码和 Cookie 在局域网内可被嗅探；**不要直接暴露到公网**，需要远程访问时用 VPN / SSH 隧道。
- 密码以 PBKDF2 哈希存储，永不回传前端；登录接口没有速率限制（局域网假设下的取舍）。
- 服务默认监听 `0.0.0.0`，登录校验不可关闭；新增接口必须挂 `require_auth`。
- 应用不执行用户上传内容（本身没有上传接口），也不提供任意路径读取。

## 11. 扩展指引

**新增 / 修改接口**：先改 `docs/API.md` → 改 `app/main.py` 的 Pydantic 模型与路由 → 补 `tests/test_api.py` → 最后接前端。前端只允许调用契约内的接口。

**新增图片字段**：改 `SCHEMA`、`to_item()`、列表查询与 `docs/API.md`，并补测试；已有数据库要写兼容迁移，不能要求用户删库。

**新增物理操作**：必须显式、可逆、不删除文件，并同步 README 与 AGENTS 中的产品规则；不要把文件移动塞进普通 Meta 操作。

**性能边界**：列表每页默认 60、最大 200；每次列表都会算全局统计；图片内容走文件系统而不是数据库。图库到万级时优先考虑分页、索引与缩略图缓存清理，而不是加缓存服务。

**已知取舍**：

- 「随机」排序由每次请求重新 `RANDOM()`，翻页可能重复或漏图，适合单页浏览；
- 撤回栈在内存里，刷新即丢；
- 扫描是单线程，大图库首次扫描慢，但之后是增量；
- 缩略图缓存不自动回收；
- ComfyUI PNG 内嵌 prompt / workflow 元数据尚未展示（见 README「暂未实现」）。

## 12. 相关文档

- [README](../README.md)：功能、使用与快捷键。
- [API.md](API.md)：前后端唯一契约。
- [DEPLOYMENT.md](DEPLOYMENT.md)：安装、开机自启、备份、排障。
- [DEVELOPMENT.md](DEVELOPMENT.md)：环境、测试、手动验证与发布清单。
- [AGENTS.md](../AGENTS.md)：给编码 Agent 的项目约束。
