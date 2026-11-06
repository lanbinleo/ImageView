# ImageView 开发约束

## Project Snapshot

- 是什么：本地图片打标、分类、评分与归档的单用户 Web 应用。评分/收藏/Collection 只存 SQLite；磁盘文件只在「物理整理 / 恢复」时移动。
- 阶段：v0.3.0，核心链路 + 撤回 / 灯箱 / 手机版 / 快速翻页预加载 / 一键启动与更新已完成（0.2.1 修了关闭灯箱仍显示遮罩的 CSS bug）。
- 平台：Windows 为主（跑在本机，局域网访问），代码本身跨平台；前端需同时适配桌面与手机浏览器（断点 760px，验证视口 390×844）。
- 技术：Python 3.10+（uv 管理，本机 `.venv` 为 CPython 3.12.10）+ FastAPI + uvicorn + SQLite（stdlib `sqlite3`）+ Pillow；前端为 `web/` 下的原生 HTML/CSS/JS，**无框架、无构建步骤**。

## Product Rules（改代码不得破坏）

- `score`：`null` 未评分、`0` 有明显瑕疵作废、`1..5` 星级。
- 打 `0` 分 → 自动进 Trash（`trashed=1`）；打 `1..5` → 自动移出 Trash；`score=null` 只清空分数、不改 Trash 状态。这条联动只在后端实现，前端不得重复实现。
- `loved` 是独立布尔 meta，与 Collection 无关。
- Collection 多对多；Trash 是内置集合，用 `trashed` 字段表示，不可删除。
- 除 `POST /api/organize` 与 `POST /api/restore` 外，任何操作都不得读写/移动/删除用户的图片文件。
- `missing=1` 的图默认不出现在列表与统计里；`rel_path` 以 `_trash/` 开头的行不参与 missing 标记。
- `view=all` 包含 Trash 中的图，只排除 missing。
- `Ctrl+Z` 撤回只覆盖 Meta 操作（打分 / 收藏 / Trash / Collection），实现为前端内存撤回栈 + `POST /api/images/batch {op:"state"}` 精确回填；物理整理/恢复不进入撤回栈（它们有显式的「恢复」）。
- 灯箱是 `<dialog id="lightbox">`（需叠在详情抽屉之上）；全局快捷键的「有 dialog 就禁用」判断必须排除灯箱，否则灯箱内快捷键失效。
- 自定义 `dialog` 的 CSS：基础规则必须保持 `display: none`，只在 `[open]` 里写 `display: flex`；否则作者样式会盖掉浏览器对关闭 dialog 的默认隐藏，导致一打开页面就被透明遮罩挡住（v0.2.1 修过这个 bug）。
- 灯箱可从 Ranking 大图、网格双击 / 右键、抽屉按钮打开；从 Ranking 打开时跟随当前图并支持打分后自动前进，从网格打开时锁定单张。

## Technical Decisions

- `app/main.py` 暴露 `create_app(data_dir: str | None = None)` 工厂；测试/脚本只能用工厂，不要 import 一个模块级 app。
- 环境与依赖由 **uv** 管理：`pyproject.toml` 声明依赖（含 `dev` group 的 httpx），`uv.lock` 锁定版本，`.venv/` 在本地且已 gitignore。所有命令统一走 `uv run ...`，不要用全局 pip/python 跑项目或测试。
- 画像根目录、密码哈希、会话密钥都存在 SQLite `settings` 表；只有 `host/port/data_dir` 在 `config.json`。
- 会话：PBKDF2-SHA256 密码哈希 + HMAC 签名 Cookie（`ir_sess`，30 天，HttpOnly/SameSite=Lax），无服务端会话存储。
- 缩略图：最长边 512 的 WebP，缓存在 `data/thumbs/<id>-<mtime>.webp`，URL 带 `?v=mtime` 长缓存。
- 前端只允许调用 `docs/API.md` 中的接口。
- 不引入前端框架、打包器或 CDN 资源（必须离线可用）。
- 测试用标准库 `unittest` + `fastapi.testclient`，不引入 pytest。

## Important Files

| 文件 | 职责 |
|---|---|
| `docs/API.md` | 前后端唯一契约；改接口必须先改这里 |
| `docs/ARCHITECTURE.md` `docs/DEPLOYMENT.md` `docs/DEVELOPMENT.md` | 架构设计、部署运维、开发与测试说明 |
| `app/main.py` | 应用工厂、全部路由、鉴权依赖、静态文件 |
| `app/db.py` | 表结构、查询、筛选/统计、序列化、评分联动字段 |
| `app/auth.py` | 密码哈希、会话 Cookie 签名/校验 |
| `app/scan.py` | 递归扫描、缩略图生成、物理整理/恢复 |
| `app/settings.py` | 读 `config.json`，定位 `web/` 目录 |
| `app/__main__.py` | `uv run python -m app` 启动入口 |
| `start.bat` `update.bat` | Windows 双击启动 / 更新并重启服务 |
| `run.ps1` `run.sh` | PowerShell / shell 兜底启动脚本 |
| `web/index.html` `web/app.js` `web/app.css` `web/theme.js` | 前端单页 |
| `tests/test_api.py` `tests/make_samples.py` | 测试与合成样图 |
| `pyproject.toml` `uv.lock` | 依赖声明与锁定（uv 管理） |
| `config.example.json` | 部署参数示例（复制为 `config.json` 使用） |

## Working Rules

- 契约先行：改任何接口（路径、字段、状态码、联动规则）先改 `docs/API.md`，再改 `app/` 与 `web/`。
- 前端交互/快捷键变化时同步 README 的快捷键表与 `web/index.html` 的快捷键弹窗。
- 版本号在 `pyproject.toml` 的 `project.version` 与 `app/__init__.py` 的 `__version__` 两处同步；发版时同时更新 README 更新日志与发行包文件名。
- 不修改与当前任务无关的既有代码；不为了让测试通过去改契约语义。
- 不执行 `git add` / `git commit` / 推送，除非用户明确要求。
- 运行数据（`data/`）、`config.json`、测试样图（`tests/samples/`）不得提交。

## Data and Security

- 用户数据：`data/rating.db`（评分、收藏、Collection、根目录、密码哈希、会话密钥）、`data/thumbs/`（缓存）。
- 密码以 PBKDF2 哈希存储，永不回传前端；会话密钥随机生成后存 `settings`，泄露需删除该行重新登录。
- 服务默认监听 `0.0.0.0`，必须保留登录校验；不要新增未鉴权的数据接口或静态目录穿越。
- 失败处理：整理/恢复移动失败只记录在响应 `failed` 中，不回滚已成功的项；数据库写入每次都 commit，异常时 rollback。

## Verification

```powershell
uv run python -m unittest discover -s tests -v      # 全部自动化测试
uv run python tests/make_samples.py --out .\tests\samples --count 24 --flawed 6
uv run python -m app                                # 本地起服务，浏览器验证
```

必须在真实浏览器确认（自动化测试覆盖不到）：Ranking 大图/快捷键手感、缩略图与自动前进、物理整理后页面状态、局域网另一台设备登录访问。

## Branching and Commits

- 单分支 `main`，项目由个人维护。
- 提交信息用 Conventional Commits（`feat: …`、`fix: …`、`docs: …`），按意图拆分。
- 何时提交由维护者决定，Agent 不主动提交。

## Definition of Done

- `uv run python -m unittest discover -s tests -v` 全绿。
- 改动的行为有对应测试或明确记为仅人工验证项。
- `docs/API.md` 与 `README.md` 中受影响的描述已同步。
- `git status --short` 中没有 `data/`、`config.json`、`tests/samples/`、`.venv/`、`__pycache__`。

## Open Decisions

- 按 Collection 物理归档到各自文件夹：用户当前明确只要「Trash → `_trash/`」这一种物理操作，暂不实现。
- 多用户/权限：明确不做，单密码单用户。
- 图片物理删除：明确不做，避免误删；`_trash/` 由用户自行清理。
