# ImageView 部署与运维

本文面向实际部署者，覆盖安装、配置、一键启动、双击更新、开机自启、备份恢复、日常运维和故障排查。
系统结构与关键规则见 [ARCHITECTURE.md](ARCHITECTURE.md)，接口见 [API.md](API.md)。

## 1. 部署形态

一台长期运行的 Windows 主机（也支持 Linux / macOS），ImageView 扫描本机或挂载的图片目录，
浏览器在**同一台机器或同一局域网**访问。单用户、单密码，不需要数据库服务，不依赖公网。

```
Windows 主机
├─ ImageView（本仓库，依赖由 uv 管理）
│   ├─ start.bat / run.ps1     一键启动
│   ├─ update.bat / update.ps1 双击更新
│   ├─ run.sh                  Linux / macOS 启动脚本
│   ├─ data/rating.db          评分与配置
│   └─ data/thumbs/            缩略图缓存
└─ <图片目录>                  被扫描的图片
    └─ _trash/                 物理整理后的图
```

## 2. 前置条件

- Windows 10 / 11（主要验证环境）；Linux / macOS 用 `run.sh`。
- [uv](https://docs.astral.sh/uv/) 0.6+。`start.bat` 会自动定位 uv，找不到时可确认后自动安装；
  也可以按第 3 节手动安装。Python 3.10+ 由 uv 负责准备，不需要手动装。
- 一个存放图片的目录，且启动服务的系统账户有**读**权限（物理整理 / 恢复额外需要**写**权限）。
- 局域网固定 IP 或路由器 DHCP 保留，避免重启后访问地址变化。
- 想用 `update.bat` 一键更新的话，需要 **git**，且项目是 `git clone` 得到的目录。

## 3. 安装

1. 获取代码：`git clone <仓库地址>`，或下载 zip 解压，放到任意目录，例如 `D:\Apps\ImageView`。
2. 双击 `start.bat`（推荐）：

   - 自动定位 uv：依次检查 PATH、常见安装位置（`%USERPROFILE%\.local\bin`、pip 用户目录等），
     最后尝试 `python -m uv`；都找不到时，窗口会询问是否自动安装（需要联网）。
   - 手动安装 uv（任选其一），装好后重新双击 `start.bat`：

     ```powershell
     winget install --id=astral-sh.uv -e
     python -m pip install uv
     ```

   - 自动执行 `uv sync`：按 `pyproject.toml` / `uv.lock` 创建 `.venv` 并安装依赖。
     首次下载依赖可能需要几十秒，之后是秒级。
   - 读取 `config.json`（没有就用默认 `host=0.0.0.0` / `port=17900` / `data_dir=data`），然后分三种情况：
     端口已有本服务 → 只打开浏览器、不重复启动；端口空闲 → 启动服务；
     端口被别的程序占用 → 窗口停住，显示占用进程和排查命令。
   - 服务就绪后自动打开 `http://127.0.0.1:17900`，窗口保留服务日志。

3. 也可以手动兜底启动（与 `start.bat` 等价，但没有窗口停住逻辑）：

   ```powershell
   .\run.ps1          # Windows PowerShell 5.1 / 7 均可
   ```

   ```bash
   ./run.sh           # Linux / macOS，首次先 chmod +x run.sh
   ```

   两者都等价于 `uv run python -m app`。

4. 日志出现以下内容即启动成功（同时会打印局域网访问地址）：

   ```
   INFO:     Uvicorn running on http://127.0.0.1:17900
   ```

   服务运行期间控制台窗口保留日志；关闭窗口或按 `Ctrl+C` 停止服务。

5. 窗口行为：**启动失败时窗口不会一闪而过**，会停住显示可读原因（任意键关闭）；
   服务正常运行期间，窗口一直保留运行日志。

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
- `config.json` 已被 `.gitignore` 忽略，不会进版本库，更新代码时也不会被覆盖。
- `start.bat` / `update.bat` 读取的是项目根目录的 `config.json`；端口被占用时给出的提示就是按它判断的。
- 高级用法：环境变量 `IR_CONFIG` 指向另一份配置文件，适合测试 / 多实例调试：

  ```powershell
  $env:IR_CONFIG = 'D:\ir-test\config.json'
  .\run.ps1
  ```

## 5. 一键启动细节（Windows）

`start.bat` 只做三件事：把控制台切到 UTF-8、选择 Windows PowerShell（找不到时用 PowerShell 7+）、
调用 `run.ps1` 并在失败时停住窗口。真正的逻辑在 `run.ps1`：

1. 定位并确认 uv 可用（需要时会引导安装）。
2. 读取配置，计算访问地址。
3. 用 `GET /api/session` 判断该端口上的是不是本服务：是就只打开浏览器并正常退出（不会重复启动）。
4. `uv sync` 同步依赖。
5. 用 `uv run python -m app` 启动服务，轮询到就绪后自动打开浏览器。
6. 阻塞等待服务结束，日志实时显示在本窗口；服务异常退出时打印退出码并保留窗口。

停止服务：直接关闭服务窗口，或在窗口里按 `Ctrl+C`。

可用环境变量 / 参数：

| 名称 | 作用 |
|---|---|
| `IR_CONFIG` | 指定另一份配置文件（默认项目根目录的 `config.json`） |
| `run.ps1 -NoBrowser` | 启动成功后不自动打开浏览器（计划任务、开机自启时用） |
| `IR_NO_BROWSER=1` | 同上，环境变量形式；对 `run.ps1` 和 `update.bat` 触发的重启都生效 |

再次双击 `start.bat` 不会产生第二个服务实例：检测到已有实例时只会打开浏览器。

## 6. 双击更新（Windows）

`update.bat` 适合 `git clone` 得到的目录，双击后由 `update.ps1` 执行：

1. 检查 git、uv、PowerShell 环境。
2. 检查当前目录是 git 工作区、位于仓库根目录、存在 `origin`、当前分支可用。
3. 检查**工作区干净**：有未提交改动就列出并中止（不会丢弃你的改动）。
4. `git fetch origin`，与 `origin/<当前分支>` 比较：
   - 已是最新 → 明确提示「已是最新版本」，继续后面的同步与重启；
   - 落后 → `git pull --ff-only` 并列出新提交；
   - 已分叉 / 本地领先 / 拉取失败 → 停止并给出处理建议。
5. `uv sync` 同步依赖。
6. **安全停止旧服务**：只停止「本项目目录 + `python -m app` + 配置里的端口」三者都能对应上的进程
   （包括它所在的启动窗口）；端口被其他程序占用时**中止更新，不停止任何进程**，并提示占用者。
7. 用 `start.bat` 在新窗口重启服务，等 `/api/session` 就绪后提示更新完成。

注意事项：

- 更新**不会**改动 `data/`、`config.json` 和图片文件，也不会删除任何用户文件。
- 用 zip 下载的用户不适用一键更新：重新下载覆盖代码即可，`data/` 与 `config.json` 保持不动。
- 更新窗口成功/失败都会保留：成功提示后按任意键关闭；失败会显示原因并停住。
- 更新过程中若脚本自身被更新，新脚本从下次运行起生效。

## 7. 首次访问与配置

1. 浏览器打开 `http://127.0.0.1:17900`。
2. 首次会要求**设置访问密码**（至少 4 位）。建议用长一点的密码：系统走 HTTP 明文，密码强度是唯一门槛。
3. 进入「设置」，把**图库根目录**填成存放图片的目录，例如 `D:\Pictures`。保存后会自动开始扫描。
4. 扫描完成后，侧栏会出现「全部 / 未评分 / ★1–5 / 收藏 / Trash」及 Collection 列表，就可以开始评分。
5. 也可以随时点顶栏的 ⟳ 手动增量扫描。

> 不建议把图库根目录设成项目目录或盘符根目录：会把无关图片（包括本仓库的截图）扫进来。扫描会跳过隐藏目录、`_trash/` 和 `data_dir`，但不会猜测哪些图是你想要的。

## 8. 局域网访问

1. 查本机 IPv4 地址：

   ```powershell
   ipconfig
   # 或
   Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' }
   ```

2. Windows 首次启动 uvicorn 时可能弹出防火墙提示，勾选**专用网络**并允许；错过了就手动放行（管理员 PowerShell）：

   ```powershell
   New-NetFirewallRule -DisplayName "ImageView 17900" -Direction Inbound `
     -Protocol TCP -LocalPort 17900 -Action Allow -Profile Private
   ```

3. 手机 / 另一台电脑打开 `http://<主机IP>:17900`，输入同一个密码。

连不上时按顺序检查：服务是否在跑（本机 `127.0.0.1` 能否打开）→ 防火墙是否放行 → 两台设备是否同一网段 → 路由器是否开了 AP 隔离（访客网络常见）。

## 9. 开机自启

### Windows（任务计划程序）

把下面命令里的路径改成实际项目路径后，在管理员 PowerShell 执行一次：

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\Apps\ImageView\run.ps1" -NoBrowser'
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName 'ImageView' -Action $action -Trigger $trigger
```

- 登录 Windows 后自动在后台启动，不弹控制台窗口，也不自动打开浏览器（`-NoBrowser`）。
- 删除：`Unregister-ScheduledTask -TaskName 'ImageView'`。
- 计划任务方式看不到窗口和日志；排查时先停用计划任务，再用 `start.bat` 手动启动一次。
- 想用当前账户运行且不需要管理员权限时，在任务计划程序界面创建任务、勾选「只在用户登录时运行」即可。
- 简单替代方案：把 `start.bat` 的快捷方式放进「启动」文件夹（`Win+R` → `shell:startup`），
  代价是会留一个控制台窗口（方便看日志），并会在登录后自动打开浏览器。

### Linux（systemd）

```ini
# /etc/systemd/system/imageview.service
[Unit]
Description=ImageView
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/opt/ImageView
ExecStart=/usr/local/bin/uv run python -m app
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now imageview
```

`ExecStart` 里的 uv 路径用 `command -v uv` 确认；`User` / `WorkingDirectory` 按实际修改。
Linux 下不需要浏览器自动打开，`run.sh` / systemd 都只启动服务。

## 10. 数据与备份

### 10.1 哪些文件需要备份

| 路径 | 内容 | 是否必须备份 |
|---|---|---|
| `data/rating.db`（及同名 `-wal` / `-shm`） | 评分、收藏、Collection、Trash、根目录、密码哈希、会话密钥 | **必须**，备份它就能保住全部记录 |
| `config.json` | 端口 / 监听地址 / 数据目录（可选文件） | 建议，恢复部署参数 |
| `data/thumbs/` | 缩略图缓存 | 不需要，删除后自动重建 |
| 图片本身 | 用户自己的图片文件 | 由用户自行备份，ImageView 不管理 |

### 10.2 在线备份（服务不用停）

SQLite 处于 WAL 模式，直接复制 `rating.db` 可能漏掉还留在 `-wal` 里的数据。推荐用 SQLite 自带的备份 API：

```powershell
uv run python -c "import sqlite3; s = sqlite3.connect('data/rating.db'); d = sqlite3.connect('rating-backup.db'); s.backup(d); d.close(); s.close()"
```

把生成的 `rating-backup.db` 挪到安全位置即可。图库很大时这条命令也只是复制数据库，速度取决于评分数据量（通常很小）。

### 10.3 恢复

1. 停止服务（关掉控制台窗口 / 停止计划任务 / `systemctl stop imageview`）。
2. 备份当前 `data/` 目录（以防选错文件）。
3. 用备份文件覆盖 `data/rating.db`，并删除 `data/rating.db-wal`、`data/rating.db-shm`（旧 WAL 不能和新库混用）。
4. 启动服务，打开页面验证评分与 Collection 是否恢复。

### 10.4 迁移到另一台机器

复制项目目录（不含 `.venv/`）→ 复制 `data/rating.db`（与可选 `config.json`）→ 在新机器启动。
若两台机器的图片路径不同，启动后在设置里改「图库根目录」并重新扫描：评分按 `rel_path` 匹配，只要相对路径一致就能接上；对不上的图会按缺失处理。

## 11. 升级与回滚

1. 先按 10.2 备份数据库（**升级前备份是硬要求**）。
2. 推荐双击 `update.bat` 一键更新：校验 git 工作区 → 拉取代码 → `uv sync` → 停旧服务 → 新窗口重启，
   全程不需要手动动数据。
3. 手动更新：停服务 → `git pull` → 双击 `start.bat` 启动（`uv sync` / `uv run` 会自动同步依赖）。
4. 当前表结构只做 `CREATE TABLE IF NOT EXISTS`，没有迁移框架；若发版说明提到字段或索引变化，按说明处理。
5. 回滚：停止服务 → 切回旧版本代码（`git checkout <旧提交>`）→ 如数据库结构已被新版本改动，
   用升级前的备份覆盖数据库 → 重新启动。

## 12. 日常运维

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

应用**不会删除图片文件**。确认不再需要这些图后，可以自行删除 `<图片目录>/_trash/` 里的文件。
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

## 13. 故障排查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| 双击后窗口一闪就关、看不到报错 | 旧版脚本 / 直接运行报错退出 | 当前 `start.bat`、`update.bat` 在失败时会停住窗口；若仍一闪，打开 cmd 手动执行 `start.bat` 看输出 |
| 中文乱码（「锟斤拷」/方块） | `.ps1` 不是 UTF-8 BOM，或被编辑器另存成了 ANSI | 用 `git checkout -- run.ps1 update.ps1` 恢复脚本；编辑器保存时选「UTF-8 with BOM」；`start.bat` 已 `chcp 65001`，不要手工改它的编码 |
| 双击 `start.bat` 只打开浏览器，不显示启动过程 | 检测到本服务已在运行，属正常行为 | 要重启就先关闭原来的服务窗口再双击 |
| 提示「未找到 uv」 | 未安装 uv，或 PATH 未生效 | 按窗口提示确认自动安装；或手动 `winget install --id=astral-sh.uv -e` / `python -m pip install uv`，然后重新双击 |
| 启动报端口占用（`10048` / `address already in use`） | 端口被其他程序或旧实例占用 | `start.bat` 会显示占用进程；用 `netstat -ano \| findstr :17900` 确认，关闭占用者或改 `config.json` 的 `port` |
| 双击 `update.bat` 提示工作区有未提交改动 | 工作区不干净 | `git status` 查看改动；提交或 `git stash` 后重试（脚本不会丢弃你的改动） |
| 双击 `update.bat` 提示不是 git 工作区 / 没有 origin | 项目是 zip 解压的，或未配置远程 | 一键更新只适用于 `git clone`；zip 用户重新下载覆盖代码即可，`data/` 与 `config.json` 不受影响 |
| 双击 `update.bat` 提示 fetch / pull 失败 | 网络、代理、git 凭据或分支已分叉 | 检查网络与凭据；手动 `git pull` 看具体报错；分叉时按提示先处理分支 |
| 双击更新后窗口显示「[更新失败]」并停住 | 更新脚本把可读原因打印在窗口里，不会闪退 | 按窗口提示处理，常见原因是工作区不干净、网络、分叉、端口被占用；修复后重新双击 `update.bat` |
| 更新停掉了服务，但新服务没起来 | 依赖同步失败、端口变化、新窗口里报错 | 查看新打开窗口的日志；修复后双击 `start.bat` 重试 |
| 更新时提示端口被其他程序占用并中止 | 安全保护：无法确认占用者属于本项目，拒绝误杀 | 关闭占用端口的程序，或修改 `config.json` 的 `port` 后重试 |
| 本机能开，局域网设备打不开 | 防火墙、监听地址、AP 隔离 | 确认 `host` 为 `0.0.0.0`；放行专用网络；检查是否同一网段 |
| 页面打开先出现一屏透明遮罩 / 只有按钮 | 旧版本灯箱 `dialog` CSS bug | 升级到最新版本；强制刷新（`Ctrl+F5`）清缓存 |
| 登录后又被踢回登录页 | Cookie 被浏览器拦截、访问地址变化 | 允许本站 Cookie；统一用同一个 IP / 域名访问；仍不行就重置密码 |
| 扫描后图片数为 0 | 根目录填错、无读权限、扩展名不支持 | 设置页确认目录存在；检查扫描状态里的 `error` |
| 图显示不出来（404） | 文件被移动 / 删除、路径变化 | 重新扫描；确认「图库根目录」指向正确位置 |
| 缩略图一直 404 | 图片损坏或 Pillow 读不了 | 用其他软件确认图片可打开；扫描 `errors` 计数可作参考 |
| 操作报数据库 locked | 同时跑了两个实例，或扫描正在写 | 只保留一个服务实例（`start.bat` 已避免重复启动）；等扫描结束再试 |
| 物理整理失败 | 图不在 Trash、文件已缺失、目标重名 | 看响应 `failed` 里的原因；先确认图在 Trash 视图且文件存在 |
| 恢复失败「原位置已被占用」 | 原路径被新文件或数据库记录占用 | 移走占用文件后重试；或手动把 `_trash/` 里的文件放回原路径 |
| 手机版样式错乱 | 浏览器缓存或旧版本 | 强制刷新；确认视口为手机模式；断点 760px |
| 想换端口 / 只允许本机访问 | 配置需要修改 | 改 `config.json` 后重启服务 |

日志直接看启动终端；通过计划任务启动时看不到窗口，可先停用任务，再用 `start.bat` / `run.ps1` 手动启动一次排查。
需要更多信息时，可在 cmd 里执行 `start.bat > startup.log 2>&1`，日志会写进文件。

## 14. 安全建议

- **不要暴露到公网**。没有 HTTPS、没有登录限速，HTTP 明文密码只适合可信局域网。
- 需要远程访问时，用 WireGuard / Tailscale 等 VPN，或 SSH 端口转发到本机 17900。
- 密码至少 8 位，不要复用其他站点密码。
- 运行服务的系统账户只需要读图片目录；只有用到物理整理 / 恢复才需要写权限。
- 备份文件包含密码哈希与会话密钥，按敏感数据处理，不要随手传到公共位置。
- 未登录时只能看到登录页，所有 `/api/*` 数据接口都会校验会话；新增接口时不要绕过鉴权。
- 启动 / 更新脚本只在本机运行 git、uv 和本项目服务；`update.bat` 停止进程前会校验进程身份，不会误杀其他程序。

## 15. 相关文档

- [README](../README.md)：功能、快捷键、常见问题。
- [ARCHITECTURE.md](ARCHITECTURE.md)：数据模型、扫描与整理的实现细节。
- [DEVELOPMENT.md](DEVELOPMENT.md)：本地开发、测试与发布清单。
- [API.md](API.md)：前后端接口契约。
