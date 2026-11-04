# ImageRating 开发指南

面向修改代码的人（包括编码 Agent）。系统设计见 [ARCHITECTURE.md](ARCHITECTURE.md)，接口契约见 [API.md](API.md)，部署见 [DEPLOYMENT.md](DEPLOYMENT.md)，必须遵守的产品规则见 [AGENTS.md](../AGENTS.md)。

## 1. 环境与依赖

- Windows 为主（也支持 Linux / macOS），Python 3.10+。
- 依赖统一由 **uv** 管理：声明在 `pyproject.toml`，锁定在 `uv.lock`，本地虚拟环境 `.venv/`（已 gitignore）。
- **不要**用全局 `pip` / `python` 跑这个项目，统一 `uv run ...`。

```powershell
# 首次会创建 .venv 并按 uv.lock 安装依赖
uv run python -m app

# 加依赖（会改 pyproject.toml + uv.lock，两个文件一起提交）
uv add <包名>
uv add --dev <包名>
```

## 2. 目录结构

```
ImageRating/
├─ app/                 后端（FastAPI）
│  ├─ __init__.py       版本号
│  ├─ __main__.py       python -m app 启动入口（读 config.json）
│  ├─ main.py           应用工厂、全部路由、鉴权依赖、静态文件
│  ├─ db.py             SQLite 表结构、查询、统计、序列化
│  ├─ auth.py           PBKDF2 密码哈希、会话 Cookie 签名
│  ├─ scan.py           扫描、缩略图、物理整理 / 恢复
│  └─ settings.py       读 config.json、定位 web/
├─ web/                 前端单页（无构建）
│  ├─ index.html        页面骨架与所有 dialog
│  ├─ app.js            状态、渲染、事件、API、撤回栈
│  ├─ app.css           主题变量、布局、响应式
│  └─ theme.js          首帧主题注入
├─ tests/
│  ├─ test_api.py       HTTP 集成测试（unittest + TestClient）
│  └─ make_samples.py   合成样图生成器
├─ docs/                API / 架构 / 部署 / 开发 / 截图
├─ config.example.json  部署配置示例（复制为 config.json）
├─ run.ps1 / run.sh / start.bat  启动脚本
├─ pyproject.toml / uv.lock     依赖声明与锁定
└─ AGENTS.md            编码 Agent 的项目约束
```

## 3. 日常开发

```powershell
# 起服务（默认 0.0.0.0:17900，数据在 data/）
uv run python -m app

# 全量测试（约 30 秒）
uv run python -m unittest discover -s tests -v

# 只跑某个类 / 某个用例
uv run python -m unittest tests.test_api.TestRating -v
uv run python -m unittest tests.test_api.TestAuth.test_login_rules -v

# 生成合成样图（用于手动看 Ranking 手感；tests/samples/ 已被 gitignore）
uv run python tests/make_samples.py --out .\tests\samples --count 24 --flawed 6
```

开发时建议：

- 用独立的 `data_dir` 起一个「开发实例」，不要污染真实评分数据（`.dev-data/` 已被 gitignore）：

  ```powershell
  uv run python -c "from app.main import create_app; import uvicorn; uvicorn.run(create_app(data_dir='.dev-data'), host='127.0.0.1', port=17901)"
  ```

  然后把图库根目录设成 `tests/samples`，用样图调试界面。

- 改前端后强刷（`Ctrl+F5`）或临时关掉浏览器缓存；`/`、`/app.css`、`/app.js` 都带 `no-cache`，正常刷新即可拿到新代码。
- 调试接口优先看浏览器 DevTools 的 Network；后端日志在启动终端。

## 4. 改动流程

1. **契约先行**：接口路径、字段、状态码、联动规则有任何变化，先改 `docs/API.md`。
2. **后端**：改 `app/main.py`（路由 / 模型）与对应模块；评分→Trash 联动只能改 `app/db.py` 的 `rated_score_fields()`。
3. **测试**：在 `tests/test_api.py` 补按契约断言的用例；跑全量测试。
4. **前端**：只调用契约内接口；交互 / 快捷键变化同步 README 快捷键表与 `web/index.html` 的快捷键弹窗。
5. **文档**：README、`docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md` 里受影响的内容一起更新。
6. **版本**：`pyproject.toml` 的 `project.version` 与 `app/__init__.py` 的 `__version__` 两处同步。

## 5. 后端开发要点

- **应用工厂**：只能用 `create_app(data_dir: str | None = None)`，测试和脚本不要 import 模块级 app。`data_dir` 传了就同时决定数据库与缩略图目录。
- **路由**：数据接口一律挂 `dependencies=[Depends(require_auth)]`；数据库连接用 `Depends(get_db)`，请求结束自动关闭。
- **错误**：抛 `HTTPException(状态码, "中文错误信息")`，前端直接展示 `detail`。注意会话失效用 401，业务校验失败用 400（前端会把 401 当成需要重新登录）。
- **配置**：只有 `host` / `port` / `data_dir` 在 `config.json`；图片根目录、密码、会话密钥都在 SQLite `settings` 表。新增运行期配置请进 `settings`，不要往 `config.json` 加。
- **序列化**：所有图片 JSON 都走 `db.to_item()`，保证字段与 `docs/API.md` 一致；`organized`、`thumb_url` 等是派生字段。
- **查询**：筛选与排序集中在 `db._where()` / `db.SORTS`；新增视图要同时改契约、前端侧栏与测试。
- **扫描**：后台线程 + 进程内状态（`app.state.scan`）；新增扫描规则时同步 `docs/API.md` 的扫描规则列表。扫描只写数据库，不动文件。
- **文件移动**：除 `app/scan.py` 的 `organize()` / `restore()` 外，任何代码都不能移动 / 删除用户图片。
- **提交与回滚**：每个请求内的写操作及时 commit；整理 / 恢复逐张处理，失败写进响应 `failed`，不回滚已成功的项。

## 6. 前端开发要点

- **零构建**：新增页面 / 组件直接改 `web/` 下的 HTML/CSS/JS；不要引入框架、打包器、CDN 或 `type="module"` 之外的构建产物。离线必须可用。
- **状态**：`app.js` 顶部 `state` 是唯一状态源；新增状态字段时想清楚刷新 / 切视图时是否要重置。
- **接口调用**：统一走 `api(method, path, body)`；401 自动回登录页。新增请求前先确认 `docs/API.md` 已有该接口。
- **DOM**：所有元素在 `index.html` 里声明，用 `id` 引用；渲染函数负责填充，不要在 JS 里拼整页 HTML。
- **弹层**：统一用 `<dialog>`；基础样式保持 `display: none`，只在 `[open]` 里 `display: flex`（v0.2.1 的透明遮罩 bug 就是违反了这条）。
- **快捷键**：统一在 `document` 的 keydown 里处理，先排除输入框聚焦与「有非灯箱 dialog 打开」；灯箱必须继续响应打分 / 切图。改快捷键同步三处：README、`index.html` 的帮助弹窗、keydown 实现。
- **响应式**：断点 760px；改布局后在 390×844 视口过一遍 Ranking、Grid、灯箱、抽屉。
- **本地存储**：主题 `theme`、筛选 `ir.filter`、排序 `ir.sort`；新增持久化键用 `lsGet` / `lsSet` 包裹（隐私模式下会抛异常）。
- **撤回**：只覆盖 Meta 操作；新增可撤回操作时先 `pushMetaUndo()` 记录旧值，再发请求；物理整理 / 恢复不要进撤回栈。

## 7. 测试

测试用标准库 `unittest` + `fastapi.testclient`（不引入 pytest），每个用例在临时目录里创建独立应用与图片根目录，绝不读写仓库里的 `data/`。

| 测试类 | 覆盖内容 |
|---|---|
| `TestAuth` | 未登录 401、首次设置、登录 / 登出、会话标志 |
| `TestScan` | 递归导入、增量扫描、新文件、删除后标记缺失 |
| `TestRating` | 1–5 分、0 分进 Trash、1–5 恢复、null 只清分数、非法分数 |
| `TestLoved` | 收藏独立于评分与筛选 |
| `TestCollections` | 创建 / 重名 / 改名 / 删除、多对多、计数 |
| `TestBatch` | 批量打分 / 收藏 / Trash、`op:"state"` 精确回填与校验 |
| `TestStats` | 统计口径（含 Trash、missing、scores） |
| `TestOrganize` | 物理整理 / 恢复、重名后缀、恢复冲突、扫描不误标缺失 |
| `TestImageContent` | 缩略图 WebP/512、原图字节与 Content-Type、鉴权、404 |
| `TestSettings` | 读设置、非法根目录、改密码、改根目录触发扫描 |

写新测试的套路：

```python
class TestSomething(ApiTestCase):
    def test_xxx(self):
        samples = self.add_samples(count=2, flawed=1)   # 生成样图并扫描
        item = next(iter(samples.values()))
        data = self.post_json(f"/api/images/{item['id']}/rate", {"score": 3})
        self.assertEqual(data["item"]["score"], 3)
```

- `ApiTestCase.setUp()` 已经建好临时 `data_dir`、图片根目录、设置密码并完成首次扫描准备。
- 扫描是异步的，用 `self.scan()` / `self.wait_scan()` 等它结束，不要 `sleep`。
- 断言以 `docs/API.md` 为准，不要照抄实现细节。
- 需要真实图片时用 `make_samples.generate()`；`tests/samples/` 只是本地生成物，不进版本库。

## 8. 手动验证清单

自动化测试覆盖不到的部分，改完必须在真实浏览器过一遍：

- [ ] Ranking：大图居中、`1`–`5` 打分后自动前进、`0` 作废进 Trash、`L` 收藏、`←/→` 切换
- [ ] 灯箱：Ranking 按 `F` / 点大图打开，打分后跟随前进；网格双击 / 右键 / 抽屉按钮打开且锁定单张；`Esc` 关闭后遮罩完全消失
- [ ] `Ctrl+Z`：打分、收藏、Trash、Collection 都能逐步撤回，撤回后统计与列表一致
- [ ] Grid：无限滚动、Ctrl/Shift 多选、框选、批量操作、右键菜单
- [ ] Collection：新建 / 改名 / 删除、加图 / 移出、重名提示
- [ ] 物理整理 / 恢复：整理后文件出现在 `_trash/`、页面显示已整理、恢复后回到原位
- [ ] 手机（390×844）：Ranking、Grid 两列、灯箱、抽屉、设置页都可操作
- [ ] 局域网另一台设备：能登录并使用
- [ ] 深色 / 浅色主题切换后刷新不闪烁

## 9. 发布检查清单

1. `uv run python -m unittest discover -s tests -v` 全绿。
2. 第 8 节手动清单过完（至少 Ranking、灯箱、手机、整理 / 恢复）。
3. `docs/API.md`、README、`docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md` 中受影响的内容已更新。
4. `pyproject.toml` 与 `app/__init__.py` 版本号一致。
5. README「更新日志」补上本版本条目。
6. `git status --short` 干净，确认没有 `data/`、`config.json`、`tests/samples/`、`.venv/`、`__pycache__`。
7. 提交信息用 Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:`），按意图拆分。
8. 如果要打包发给别人，文件名带版本号（例如 `ImageRating-v0.2.1.zip`），并排除 `.venv/`、`data/`、`config.json`、`tests/samples/`。

## 10. 常见开发问题

| 问题 | 处理 |
|---|---|
| `uv: command not found` | 安装 uv（见 README / DEPLOYMENT），重开终端 |
| `uv run` 很慢 | 首次要下载依赖；之后命中缓存。别用 `--no-sync` 跳过同步 |
| 测试卡住 | 多半是扫描没结束就退出；用 `wait_scan`，超时看最后 status |
| 端口被占用 | 加 `--port` 或改 `config.json`；本机调试固定用 127.0.0.1 |
| 改了前端没生效 | 强刷；确认没有被 `python -m app` 之外的旧进程占用端口 |
| 缩略图不更新 | 图片内容变了但 size/mtime 没变（少见）；重新扫描并删 `data/thumbs/` 对应文件 |
| 数据库越用越大 | WAL 文件正常；缩略图在 `data/thumbs/`，可整体删除重建 |
| 测试污染 `data/` | 不应该发生：测试只用 `create_app(data_dir=临时目录)`；发现说明有人绕过了工厂 |

## 11. 文档维护

| 改动 | 必须同步 |
|---|---|
| 接口 / 字段 / 状态码 | `docs/API.md`（先改） |
| 用户可见功能 / 快捷键 | `README.md` + `web/index.html` 帮助弹窗 |
| 产品规则 / 数据模型 | `AGENTS.md` + `docs/ARCHITECTURE.md` |
| 部署方式 / 运维操作 | `docs/DEPLOYMENT.md` |
| 开发流程 / 测试方式 | 本文件 |
| 发版 | README 更新日志 + 两处版本号 |

## 12. 相关文档

- [README](../README.md)：功能、使用、快捷键。
- [ARCHITECTURE.md](ARCHITECTURE.md)：模块、数据模型、并发与安全。
- [DEPLOYMENT.md](DEPLOYMENT.md)：安装、备份、运维、排障。
- [API.md](API.md)：前后端唯一契约。
- [AGENTS.md](../AGENTS.md)：不可破坏的产品规则与协作约束。
