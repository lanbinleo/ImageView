# ImageRating 部署与运维

本文面向实际部署者，覆盖安装、配置、开机自启、备份恢复、日常运维和故障排查。
系统结构与关键规则见 [ARCHITECTURE.md](ARCHITECTURE.md)，接口见 [API.md](API.md)。

## 1. 部署形态

一台跑 ComfyUI 的 Windows 主机（也支持 Linux / macOS）：
ComfyUI 把图写到输出目录，ImageRating 扫描该目录，浏览器在**同一台机器或同一局域网**访问。
单用户、单密码，不需要数据库服务，不依赖公网。

```
ComfyUI 主机
├─ ComfyUI                （出图，写 <输出目录>）
├─ ImageRating            （本仓库，uv 管理）
│   ├─ data/rating.db     评分与配置
│   └─ data/thumbs/       缩略图缓存
└─ <输出目录>             被扫描的图片根目录
    └─ _trash/            物理整理后的图
```

## 2. 前置条件

- Windows 10 / 11（主要验证环境），或 Linux / macOS。
- [uv](https://docs.astral.sh/uv/) 0.6+；Python 3.10+ 由 uv 负责准备，不需要手动装。
- 一个存放 ComfyUI 出图的目录，且启动服务的系统账户有**读**权限（物理整理 / 恢复额外需要**写**权限）。
- 局域网固定 IP 或路由器 DHCP 保留，避免重启后访问地址变化。

## 3. 安装

1. 把仓库放到主机上（`git clone`，或直接复制目录），例如 `D:\Desktop\ImageRating`。
2. 安装 uv，任选其一：

   ```powershell
   winget install --id=astral-sh.uv -e
   python -m pip install uv
   ```

3. 进入项目目录并首次启动（会自动创建 `.venv` 并安装依赖）：

   ```powershell
   .\start.bat        # 双击也可以；窗口关掉就停止服务
   ```

   或者用 PowerShell / bash：

   ```powershell
   .\run.ps1
   ```

   ```bash
   ./run.sh           # 首次先 chmod +x run.sh
   ```

   三者都等价于 `uv run python -m app`。首次启动下载依赖可能需要几十秒，之后是秒级。

4. 日志出现以下内容即启动成功：

   ```
   ImageRating 启动中：http://127.0.0.1:17900
   同网段其他设备访问：http://192.168.x.x:17900
   ```

## 4. 配置文件

部署参数只放在 `config.json`（可选；没有就用默认值）。从示例复制：

```powershell
Copy-Item config.example.json config.json
```

```json
{
  "host": "0.0.0.0",
  "port": 17900,
  "data_dir": "data"
}
```

| 字段 | 默认 | 说明 |
|---|---|---|
| `host` | `0.0.0.0` | `0.0.0.0` 允许局域网访问；`127.0.0.1` 只允许本机 |
| `port` | `17900` | 被占用就换一个（如 `17901`），防火墙规则也要跟着改 |
| `data_dir` | `data` | 数据库与缩略图目录；相对路径基于项目根目录，也接受绝对路径 |

- 改 `data_dir` **不会**自动搬移已有数据，需要先停服务、手动移动目录。
- `config.json` 已被 `.gitignore` 忽略，不会进版本库。
- 高级用法：设置环境变量 `IR_CONFIG` 指向另一份配置文件，适合测试 / 多实例调试：

  ```powershell
  $env:IR_CONFIG = 'D:\ir-test\config.json'
  uv run python -m app
  ```

## 5. 首次访问与配置

1. 浏览器打开 `http://127.0.0.1:17900`。
2. 首次会要求**设置访问密码**（至少 4 位）。建议用长一点的密码：系统走 HTTP 明文，密码强度是唯一门槛。
3. 进入「设置」，把**图库根目录**填成 ComfyUI 的输出目录，例如 `D:\ComfyUI\output`。保存后会自动开始扫描。
4. 扫描完成后，侧栏会出现「全部 / 未评分 / ★1–5 / 收藏 / Trash」及 Collection 列表，就可以开始评分。
5. 也可以随时点顶栏的 ⟳ 手动增量扫描（ComfyUI 又出了新图之后）。

> 不建议把图库根目录设成项目目录或盘符根目录：会把无关图片（包括本仓库的截图）扫进来。扫描会跳过隐藏目录、`_trash/` 和 `data_dir`，但不会猜测哪些图是你想要的。

## 6. 局域网访问

1. 查本机 IPv4 地址：

   ```powershell
   ipconfig
   # 或
   Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' }
   ```

2. Windows 首次启动 uvicorn 时可能弹出防火墙提示，勾选**专用网络**并允许；错过了就手动放行（管理员 PowerShell）：

   ```powershell
   New-NetFirewallRule -DisplayName "ImageRating 17900" -Direction Inbound `
     -Protocol TCP -LocalPort 17900 -Action Allow -Profile Private
   ```

3. 手机 / 另一台电脑打开 `http://<主机IP>:17900`，输入同一个密码。

连不上时按顺序检查：服务是否在跑（本机 `127.0.0.1` 能否打开）→ 防火墙是否放行 → 两台设备是否同一网段 → 路由器是否开了 AP 隔离（访客网络常见）。

## 7. 开机自启

### Windows（任务计划程序）

把下面命令里的路径改成实际路径后，在管理员 PowerShell 执行一次：

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\Desktop\ImageRating\run.ps1"'
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName 'ImageRating' -Action $action -Trigger $trigger
```

- 登录 Windows 后自动在后台启动，不弹控制台窗口。
- 删除：`Unregister-ScheduledTask -TaskName 'ImageRating'`。
- 想用当前账户运行且不需要管理员权限时，在任务计划程序界面创建任务、勾选「只在用户登录时运行」即可。
- 简单替代方案：把 `start.bat` 的快捷方式放进「启动」文件夹（`Win+R` → `shell:startup`），代价是会留一个控制台窗口。

### Linux（systemd）

```ini
# /etc/systemd/system/imagerating.service
[Unit]
Description=ImageRating
After=network.target

[Service]
Type=simple
User=leo
WorkingDirectory=/opt/ImageRating
ExecStart=/usr/local/bin/uv run python -m app
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now imagerating
```

`ExecStart` 里的 uv 路径用 `command -v uv` 确认；`User` / `WorkingDirectory` 按实际修改。

## 8. 数据与备份

### 8.1 哪些文件需要备份

| 路径 | 内容 | 是否必须备份 |
|---|---|---|
| `data/rating.db`（及同名 `-wal` / `-shm`） | 评分、收藏、Collection、Trash、根目录、密码哈希、会话密钥 | **必须**，备份它就能保住全部记录 |
| `config.json` | 端口 / 监听地址 / 数据目录（可选文件） | 建议，恢复部署参数 |
| `data/thumbs/` | 缩略图缓存 | 不需要，删除后自动重建 |
| 图片本身 | 用户自己的 ComfyUI 输出 | 由用户自行备份，ImageRating 不管理 |

### 8.2 在线备份（服务不用停）

SQLite 处于 WAL 模式，直接复制 `rating.db` 可能漏掉还留在 `-wal` 里的数据。推荐用 SQLite 自带的备份 API：

```powershell
uv run python -c "import sqlite3; s = sqlite3.connect('data/rating.db'); d = sqlite3.connect('rating-backup.db'); s.backup(d); d.close(); s.close()"
```

把生成的 `rating-backup.db` 挪到安全位置即可。图库很大时这条命令也只是复制数据库，速度取决于评分数据量（通常很小）。

### 8.3 恢复

1. 停止服务（关掉控制台窗口 / 停止计划任务 / `systemctl stop imagerating`）。
2. 备份当前 `data/` 目录（以防选错文件）。
3. 用备份文件覆盖 `data/rating.db`，并删除 `data/rating.db-wal`、`data/rating.db-shm`（旧 WAL 不能和新库混用）。
4. 启动服务，打开页面验证评分与 Collection 是否恢复。

### 8.4 迁移到另一台机器

复制项目目录（不含 `.venv/`）→ 复制 `data/rating.db`（与可选 `config.json`）→ 在新机器启动。
若两台机器的图片路径不同，启动后在设置里改「图库根目录」并重新扫描：评分按 `rel_path` 匹配，只要相对路径一致就能接上；对不上的图会按缺失处理。

## 9. 升级与回滚

1. 先按 8.2 备份数据库。
2. 停止服务，更新代码（`git pull` 或覆盖文件）。
3. 启动：`uv run` 会按更新后的 `pyproject.toml` / `uv.lock` 自动同步依赖。
4. 当前表结构只做 `CREATE TABLE IF NOT EXISTS`，没有迁移框架；若发版说明提到字段或索引变化，按说明处理。**升级前备份是硬要求**。
5. 回滚：停止服务 → 切回旧版本代码（`git checkout <旧提交>`）→ 如数据库结构已被新版本改动，用升级前的备份覆盖数据库 → 启动。

## 10. 日常运维

### 修改密码

登录后在「设置 → 修改密码」操作，需要当前密码；修改后当前浏览器保持登录。

### 强制所有设备重新登录

删掉会话密钥并重启，所有已签发 Cookie 立即失效：

```powershell
# 停止服务后，在项目根目录执行
@'
import sqlite3
conn = sqlite3.connect("data/rating.db")
conn.execute("DELETE FROM settings WHERE key = 'secret'")
conn.commit()
conn.close()
print("会话密钥已删除，启动后会重新生成")
'@ | uv run python -
```

### 忘记密码（重置，不丢评分）

```powershell
# 停止服务后执行：清除密码哈希，启动后页面会重新要求「设置密码」
@'
import sqlite3
conn = sqlite3.connect("data/rating.db")
conn.execute("DELETE FROM settings WHERE key = 'password_hash'")
conn.commit()
conn.close()
print("密码已清除，启动后按页面提示重新设置")
'@ | uv run python -
```

如果 `data_dir` 改过位置，把脚本里的路径换成实际数据库路径。

### 清理缩略图缓存

停不停服务都行，直接删除 `data/thumbs/` 后重新访问页面，会按需重建。图片很多时首次加载会慢一些。

### 清理 `_trash/`

应用**不会删除图片文件**。确认不再需要这些图后，可以自行删除 `<图片根目录>/_trash/` 里的文件。
注意：数据库里的整理记录不会跟着消失，这些图仍会出现在 Trash 视图里但打不开，恢复功能也会失败。若想同时清掉记录（仅在文件确已删除时）：

```powershell
# 停止服务后执行；只删除已整理到 _trash/ 的记录，其他评分记录不受影响
@'
import sqlite3
conn = sqlite3.connect("data/rating.db")
n = conn.execute("DELETE FROM images WHERE rel_path LIKE '_trash/%'").rowcount
conn.commit()
conn.close()
print(f"已删除 {n} 条已整理记录")
'@ | uv run python -
```

### 完全重置

停止服务，删除 `data/` 目录（或 `data/rating.db`），重启即可重新设置密码和根目录。这会丢失全部评分、收藏、Collection 与配置，图片文件不受影响。

## 11. 故障排查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| 启动提示「未找到 uv」 | 未安装或 PATH 未生效 | 按第 3 节安装 uv，重开终端 |
| 启动报端口占用（`10048` / `address already in use`） | 17900 被别的进程占用 | 改 `config.json` 的 `port`；用 `netstat -ano \| findstr :17900` 找到进程 |
| 本机能开，局域网设备打不开 | 防火墙、监听地址、AP 隔离 | 确认 `host` 为 `0.0.0.0`；放行专用网络；检查是否同一网段 |
| 页面打开先出现一屏透明遮罩 / 只有按钮 | 旧版本灯箱 `dialog` CSS bug | 升级到 0.2.1 或更新；强制刷新（`Ctrl+F5`）清缓存 |
| 登录后又被踢回登录页 | Cookie 被浏览器拦截、访问地址变化 | 允许本站 Cookie；统一用同一个 IP / 域名访问；仍不行就重置密码 |
| 扫描后图片数为 0 | 根目录填错、无读权限、扩展名不支持 | 设置页确认目录存在；用 ComfyUI 的原始输出目录；检查扫描状态里的 `error` |
| 图显示不出来（404） | 文件被移动 / 删除、路径变化 | 重新扫描；确认「图库根目录」指向正确位置 |
| 缩略图一直 404 | 图片损坏或 Pillow 读不了 | 用其他软件确认图片可打开；扫描 `errors` 计数可作参考 |
| 操作报数据库 locked | 同时跑了两个实例，或扫描正在写 | 只保留一个服务实例；等扫描结束再试 |
| 物理整理失败 | 图不在 Trash、文件已缺失、目标重名 | 看响应 `failed` 里的原因；先确认图在 Trash 视图且文件存在 |
| 恢复失败「原位置已被占用」 | 原路径被新文件或数据库记录占用 | 移走占用文件后重试；或手动把 `_trash/` 里的文件放回原路径 |
| 手机版样式错乱 | 浏览器缓存或旧版本 | 强制刷新；确认视口为手机模式；断点 760px |
| 想换端口 / 只允许本机访问 | 配置需要修改 | 改 `config.json` 后重启服务 |

日志直接看启动终端；通过计划任务启动时看不到窗口，可临时用 `run.ps1` 手动启动一次排查。

## 12. 安全建议

- **不要暴露到公网**。没有 HTTPS、没有登录限速，HTTP 明文密码只适合可信局域网。
- 需要远程访问时，用 WireGuard / Tailscale 等 VPN，或 SSH 端口转发到本机 17900。
- 密码至少 8 位，不要复用其他站点密码。
- 运行服务的系统账户只需要读图片目录；只有用到物理整理 / 恢复才需要写权限。
- 备份文件包含密码哈希与会话密钥，按敏感数据处理，不要随手传到公共位置。
- 未登录时只能看到登录页，所有 `/api/*` 数据接口都会校验会话；新增接口时不要绕过鉴权。

## 13. 相关文档

- [README](../README.md)：功能、快捷键、常见问题。
- [ARCHITECTURE.md](ARCHITECTURE.md)：数据模型、扫描与整理的实现细节。
- [DEVELOPMENT.md](DEVELOPMENT.md)：本地开发、测试与发布清单。
- [API.md](API.md)：前后端接口契约。
