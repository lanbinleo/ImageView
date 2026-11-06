# ============================================================
#  ImageView 一键启动（Windows PowerShell 5.1 / 7 通用）
#
#  入口：双击 start.bat；也可以在本目录执行 .\run.ps1
#
#  流程：定位 uv → 读 config.json → 该端口已有本服务则只开浏览器
#        → uv sync → uv run python -m app → 就绪后打开浏览器
#        → 窗口保留服务日志；任何失败都由 start.bat 停住窗口
#
#  编码：本文件必须保存为「UTF-8 with BOM + CRLF」。
#        Windows PowerShell 5.1 不会把无 BOM 的 UTF-8 当 UTF-8 读，
#        中文会被解析成乱码（历史上「中文乱码」的根因）。
#
#  参数：-NoBrowser  启动成功后不自动打开浏览器（计划任务 / 开机自启用）。
# ============================================================

param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$script:ProjectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$script:ReadyTimeoutSec = 90
$script:ExitOk = 0
$script:ExitFail = 1
$script:UvExe = $null
$script:UvPrefix = @()

# 中文输出：Windows PowerShell 5.1 默认按系统代码页（中文系统为 GBK）输出，
# 与 start.bat 里的 chcp 65001 对齐，避免提示和日志显示成乱码。
try {
    $script:Utf8 = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $script:Utf8
    $OutputEncoding = $script:Utf8
} catch { }

# ------------------------------------------------------------
#  输出辅助
# ------------------------------------------------------------

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Detail([string]$Text) {
    Write-Host "    $Text"
}

function Write-Good([string]$Text) {
    Write-Host "    $Text" -ForegroundColor Green
}

function Write-Note([string]$Text) {
    Write-Host "    $Text" -ForegroundColor Yellow
}

function Write-Bad([string]$Text) {
    Write-Host "    $Text" -ForegroundColor Red
}

function Stop-WithError([string]$Text) {
    Write-Host ''
    Write-Bad "[启动失败] $Text"
    Write-Host '    排查提示见 docs/DEPLOYMENT.md 的「故障排查」一节。' -ForegroundColor DarkGray
    exit $script:ExitFail
}

function Set-WindowTitle([string]$Text) {
    try { $Host.UI.RawUI.WindowTitle = $Text } catch { }
}

# ------------------------------------------------------------
#  uv：定位 / 校验 / 兜底安装
# ------------------------------------------------------------

function Test-UvCandidate([string]$Exe, [string[]]$Prefix) {
    if ([string]::IsNullOrWhiteSpace($Exe)) { return $false }
    try {
        $out = & $Exe @($Prefix + @('--version')) 2>$null
        return ($LASTEXITCODE -eq 0 -and (($out -join ' ') -match 'uv'))
    } catch {
        return $false
    }
}

function Find-UvCommand {
    # 1) PATH
    $cmd = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $cmd) {
        $exe = [string]$cmd.Path
        if (-not $exe) { $exe = [string]$cmd.Source }
        if (Test-UvCandidate $exe @()) {
            $script:UvExe = $exe
            $script:UvPrefix = @()
            return $true
        }
    }

    # 2) 常见安装位置（官方安装脚本 / pip --user / winget / cargo）
    $patterns = @(
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\uv\uv.exe'),
        (Join-Path $env:APPDATA 'Python\*\Scripts\uv.exe')
    )
    foreach ($pattern in $patterns) {
        if ([string]::IsNullOrWhiteSpace($pattern)) { continue }
        foreach ($file in @(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue)) {
            if ($file.PSIsContainer) { continue }
            $exe = [string]$file.FullName
            if (Test-UvCandidate $exe @()) {
                $script:UvExe = $exe
                $script:UvPrefix = @()
                return $true
            }
        }
    }

    # 3) python -m uv 兜底（pip 安装的 uv 会暴露同名的 Python 模块）
    $pythons = @()
    $pyCmd = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pyCmd) {
        $pythons += ([string]$pyCmd.Path)
    }
    $pyLauncher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pyLauncher) {
        $pythons += ([string]$pyLauncher.Path)
    }
    foreach ($python in $pythons) {
        if ([string]::IsNullOrWhiteSpace($python)) { continue }
        if (Test-UvCandidate $python @('-m', 'uv')) {
            $script:UvExe = $python
            $script:UvPrefix = @('-m', 'uv')
            return $true
        }
    }

    return $false
}

function Show-UvManualHint {
    Write-Host ''
    Write-Host '    手动安装 uv（任选其一，装好后重新双击 start.bat）：'
    Write-Host '      winget install --id=astral-sh.uv -e'
    Write-Host '      python -m pip install uv'
    Write-Host '    文档：https://docs.astral.sh/uv/getting-started/installation/'
}

function Install-UvInteractive {
    if ([Console]::IsInputRedirected) {
        Write-Bad '未找到 uv，且当前环境无法交互确认自动安装，已中止。'
        Show-UvManualHint
        exit $script:ExitFail
    }
    Write-Host ''
    Write-Note '未找到 uv（本项目的 Python 环境与依赖都由 uv 管理）。'
    $answer = Read-Host '    是否现在自动安装 uv？输入 y 回车确认，其它内容取消 (y/N)'
    if ($answer -notmatch '^(y|yes|是)$') {
        Show-UvManualHint
        Stop-WithError '已取消自动安装 uv。'
    }

    $attempts = @(
        @{
            Name = 'winget';
            Action = {
                & winget.exe install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
            }
        },
        @{
            Name = '官方安装脚本';
            Action = {
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
            }
        },
        @{
            Name = 'python -m pip';
            Action = {
                $python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($null -eq $python) { throw '未找到 python，无法用 pip 安装 uv。' }
                & $python.Path -m pip install --user --upgrade uv
            }
        }
    )

    foreach ($attempt in $attempts) {
        Write-Detail ("尝试用{0}安装 uv ..." -f $attempt.Name)
        try {
            & $attempt.Action | Out-Host
        } catch {
            Write-Note ("{0} 安装失败：{1}" -f $attempt.Name, $_.Exception.Message)
        }
        if (Find-UvCommand) {
            Write-Good 'uv 安装成功。'
            return
        }
    }

    Show-UvManualHint
    Stop-WithError '自动安装 uv 没有成功，请按上面的提示手动安装后重试。'
}

# ------------------------------------------------------------
#  配置：config.json / IR_CONFIG
# ------------------------------------------------------------

function Get-ConfigPath {
    if (-not [string]::IsNullOrWhiteSpace($env:IR_CONFIG)) { return $env:IR_CONFIG }
    return (Join-Path $script:ProjectRoot 'config.json')
}

function Read-AppConfig {
    $result = [pscustomobject]@{
        Host    = '0.0.0.0'
        Port    = 17900
        DataDir = (Join-Path $script:ProjectRoot 'data')
        Path    = (Get-ConfigPath)
        Exists  = $false
    }
    if (-not (Test-Path -LiteralPath $result.Path)) {
        return $result
    }

    $result.Exists = $true
    try {
        $text = [System.IO.File]::ReadAllText($result.Path, [System.Text.Encoding]::UTF8)
        $obj = $text | ConvertFrom-Json
    } catch {
        Write-Note ("config.json 解析失败（{0}），将使用默认配置。" -f $_.Exception.Message)
        return $result
    }
    if ($obj -isnot [System.Management.Automation.PSCustomObject]) {
        Write-Note 'config.json 顶层不是 JSON 对象，将使用默认配置。'
        return $result
    }

    $prop = $obj.PSObject.Properties['host']
    if ($null -ne $prop) {
        if (($prop.Value -is [string]) -and -not [string]::IsNullOrWhiteSpace($prop.Value)) {
            $result.Host = ([string]$prop.Value).Trim()
        } else {
            Stop-WithError ("config.json 的 host 无效（应为字符串），实际值：{0}" -f $prop.Value)
        }
    }

    $prop = $obj.PSObject.Properties['port']
    if ($null -ne $prop) {
        $port = -1
        try { $port = [int]$prop.Value } catch { $port = -1 }
        if (($port -lt 1) -or ($port -gt 65535)) {
            Stop-WithError ("config.json 的 port 无效（应为 1-65535 的整数），实际值：{0}" -f $prop.Value)
        }
        $result.Port = $port
    }

    $prop = $obj.PSObject.Properties['data_dir']
    if ($null -ne $prop) {
        if (($prop.Value -is [string]) -and -not [string]::IsNullOrWhiteSpace($prop.Value)) {
            $dataDir = [string]$prop.Value
            if (-not [System.IO.Path]::IsPathRooted($dataDir)) {
                $dataDir = Join-Path $script:ProjectRoot $dataDir
            }
            $result.DataDir = [System.IO.Path]::GetFullPath($dataDir)
        } else {
            Stop-WithError ("config.json 的 data_dir 无效（应为路径字符串），实际值：{0}" -f $prop.Value)
        }
    }

    return $result
}

# ------------------------------------------------------------
#  端口 / 进程探测
# ------------------------------------------------------------

function Get-ProbeHost([string]$BindHost) {
    $h = ([string]$BindHost).Trim().ToLowerInvariant()
    if (($h -eq '') -or ($h -eq '0.0.0.0') -or ($h -eq '::') -or ($h -eq '::0') -or ($h -eq '*')) {
        return '127.0.0.1'
    }
    if ($h -eq 'localhost') { return '127.0.0.1' }
    return $h
}

function Format-Url([string]$ProbeHost, [int]$Port) {
    $hostPart = $ProbeHost
    if ($hostPart.Contains(':')) { $hostPart = '[' + $hostPart + ']' }
    return ('http://' + $hostPart + ':' + $Port)
}

function Test-ImageViewAt([string]$ProbeHost, [int]$Port) {
    # 本服务的 /api/session 固定返回 {"authed": ..., "needs_setup": ...}，
    # 用它区分「本服务已在跑」和「端口被别的程序占用」。
    $url = (Format-Url $ProbeHost $Port) + '/api/session'
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if (($null -eq $resp) -or ([int]$resp.StatusCode -ne 200)) { return $false }
        $data = $resp.Content | ConvertFrom-Json
        if ($null -eq $data) { return $false }
        $names = @($data.PSObject.Properties | ForEach-Object { $_.Name })
        return (($names -contains 'authed') -and ($names -contains 'needs_setup'))
    } catch {
        return $false
    }
}

function Get-ListenerProcessId([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($null -ne $conn) { return [int]$conn.OwningProcess }
    } catch { }
    # 没有 NetTCPIP 模块的旧系统退回 netstat
    foreach ($line in @(& netstat.exe -ano -p tcp 2>$null)) {
        if ([string]$line -match ('^\s*TCP\s+\S+:' + $Port + '\s+\S+\s+LISTENING\s+(\d+)\s*$')) {
            return [int]$Matches[1]
        }
    }
    return 0
}

function Get-ProcessSnapshot([int]$ProcessId) {
    if ($ProcessId -le 0) { return $null }
    try {
        $p = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -ErrorAction Stop
        if ($null -eq $p) { return $null }
        return [pscustomobject]@{
            Id            = [int]$p.ProcessId
            ParentId      = [int]$p.ParentProcessId
            Name          = [string]$p.Name
            ExecutablePath = [string]$p.ExecutablePath
            CommandLine   = [string]$p.CommandLine
        }
    } catch {
        return $null
    }
}

function Show-PortOwnerHint([int]$Port) {
    $ownerPid = Get-ListenerProcessId $Port
    if ($ownerPid -eq 0) { return }
    $snapshot = Get-ProcessSnapshot $ownerPid
    if ($null -ne $snapshot) {
        Write-Detail ("占用进程：PID {0}（{1}）" -f $snapshot.Id, $snapshot.Name)
        if (-not [string]::IsNullOrWhiteSpace($snapshot.ExecutablePath)) {
            Write-Detail ("可执行文件：{0}" -f $snapshot.ExecutablePath)
        }
    }
    Write-Detail ("查看占用：netstat -ano | findstr :{0}" -f $Port)
}

# ------------------------------------------------------------
#  浏览器
# ------------------------------------------------------------

function Open-Browser([string]$Url) {
    if ($NoBrowser -or ($env:IR_NO_BROWSER -eq '1')) {
        Write-Detail '（已跳过自动打开浏览器）'
        return
    }
    try {
        Start-Process -FilePath $Url -ErrorAction Stop
        Write-Good ("已在默认浏览器打开：{0}" -f $Url)
    } catch {
        Write-Note ("自动打开浏览器失败，请手动访问：{0}" -f $Url)
    }
}

# ------------------------------------------------------------
#  启动 / 等待就绪
# ------------------------------------------------------------

function Start-ImageViewService {
    # 用 .NET Process 而不是 Start-Process：Windows PowerShell 5.1 里
    # Start-Process -PassThru 返回的对象读不到 ExitCode（实测为空），
    # 服务停止后就无法判断是正常退出还是崩溃。
    $argumentList = @($script:UvPrefix) + @('run', 'python', '-m', 'app')
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $script:UvExe
    $startInfo.Arguments = ($argumentList -join ' ')
    $startInfo.WorkingDirectory = $script:ProjectRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $false
    try {
        return [System.Diagnostics.Process]::Start($startInfo)
    } catch {
        Stop-WithError ("无法启动服务进程：{0}" -f $_.Exception.Message)
    }
}

function Get-ProcessExitCode([object]$Process) {
    if ($null -eq $Process) { return $null }
    try {
        if ($Process.HasExited) { return [int]$Process.ExitCode }
    } catch { }
    return $null
}

function Wait-ServiceReady([object]$Process, [string]$ProbeHost, [int]$Port) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $script:ReadyTimeoutSec) {
        if ($Process.HasExited) { return $false }
        if (Test-ImageViewAt $ProbeHost $Port) { return $true }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Stop-StartedProcess([object]$Process) {
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            # 用 /T 连同 uv 拉起的 python 子进程一起结束，避免留下占端口的孤儿进程
            & taskkill.exe /PID $Process.Id /T /F 2>&1 | Out-Null
        }
    } catch { }
}

function Invoke-UvCommand([string[]]$UvArgs) {
    $all = @($script:UvPrefix) + @($UvArgs)
    & $script:UvExe @all | Out-Host
    return $LASTEXITCODE
}

# ------------------------------------------------------------
#  主流程
# ------------------------------------------------------------

try {
    Write-Host ''
    Write-Host '==============================================' -ForegroundColor DarkCyan
    Write-Host '  ImageView 一键启动' -ForegroundColor Cyan
    Write-Host ("  项目目录：{0}" -f $script:ProjectRoot) -ForegroundColor DarkGray
    Write-Host '==============================================' -ForegroundColor DarkCyan

    Set-WindowTitle 'ImageView 启动中'

    Write-Step '检查 uv'
    if (-not (Find-UvCommand)) {
        Install-UvInteractive
    }
    $uvDesc = $script:UvExe
    if ($script:UvPrefix.Count -gt 0) { $uvDesc = ('{0} -m uv' -f $script:UvExe) }
    Write-Good ("uv：{0}" -f $uvDesc)

    Write-Step '读取配置'
    $config = Read-AppConfig
    if ($config.Exists) {
        Write-Detail ("配置文件：{0}" -f $config.Path)
    } else {
        Write-Detail ("未找到 {0}，使用默认配置。" -f $config.Path)
    }
    $probeHost = Get-ProbeHost $config.Host
    $url = (Format-Url $probeHost $config.Port)
    Write-Detail ("监听地址：{0}，端口：{1}" -f $config.Host, $config.Port)
    Write-Detail ("数据目录：{0}" -f $config.DataDir)
    Write-Detail ("访问地址：{0}" -f $url)

    Write-Step '检查服务是否已经在运行'
    if (Test-ImageViewAt $probeHost $config.Port) {
        Write-Good '检测到 ImageView 已经在运行，不重复启动。'
        Open-Browser $url
        Write-Host ''
        Write-Detail '直接使用浏览器访问即可；如需重启，请先关闭原来的服务窗口。'
        exit $script:ExitOk
    }
    if ((Get-ListenerProcessId $config.Port) -ne 0) {
        # 端口有监听但还没响应 /api/session：给它一点启动时间再判断
        for ($i = 0; $i -lt 6; $i++) {
            Start-Sleep -Milliseconds 500
            if (Test-ImageViewAt $probeHost $config.Port) {
                Write-Good '检测到 ImageView 已经在运行，不重复启动。'
                Open-Browser $url
                Write-Host ''
                Write-Detail '直接使用浏览器访问即可；如需重启，请先关闭原来的服务窗口。'
                exit $script:ExitOk
            }
            if ((Get-ListenerProcessId $config.Port) -eq 0) { break }
        }
    }
    if ((Get-ListenerProcessId $config.Port) -ne 0) {
        Write-Detail ("端口 {0} 已被占用，且响应的不是本服务：" -f $config.Port)
        Show-PortOwnerHint $config.Port
        Stop-WithError ("端口 {0} 已被其他程序占用。请关闭它，或修改 config.json 里的 port（如 17901）后重试。" -f $config.Port)
    }
    Write-Good '端口空闲。'

    Write-Step '同步依赖（uv sync）'
    $syncCode = Invoke-UvCommand @('sync')
    if ($syncCode -ne 0) {
        Stop-WithError ("uv sync 失败（退出码 {0}）。请检查网络或代理后重试。" -f $syncCode)
    }
    Write-Good '依赖已同步。'

    # 同步依赖期间可能有人手动启动了服务，再确认一次
    if (Test-ImageViewAt $probeHost $config.Port) {
        Write-Good '检测到 ImageView 已经在运行，不重复启动。'
        Open-Browser $url
        exit $script:ExitOk
    }

    # Python 输出统一按 UTF-8：控制台与重定向日志保持一致，避免中文横幅按系统代码页输出。
    $env:PYTHONUTF8 = '1'

    Write-Step '启动服务（uv run python -m app）'
    Set-WindowTitle 'ImageView 启动中'
    $service = Start-ImageViewService

    $ready = Wait-ServiceReady $service $probeHost $config.Port
    if (-not $ready) {
        if ($service.HasExited) {
            $earlyCode = Get-ProcessExitCode $service
            if ($null -ne $earlyCode) {
                Stop-WithError ("服务进程已退出（退出码 {0}），请查看上方日志里的报错。" -f $earlyCode)
            }
            Stop-WithError '服务进程已退出，请查看上方日志里的报错。'
        }
        Stop-StartedProcess $service
        Stop-WithError ("等待服务就绪超时（{0} 秒）。首次启动需要下载依赖，请检查网络后重试。" -f $script:ReadyTimeoutSec)
    }

    Write-Host ''
    Write-Good '服务已就绪。'
    Write-Detail ("本机访问：{0}" -f $url)
    Write-Detail '服务运行期间日志会继续输出在本窗口；按 Ctrl+C 停止服务。'
    Write-Detail '关闭本窗口也会停止服务。'
    Set-WindowTitle ("ImageView - 运行中 - {0}" -f $url)
    Open-Browser $url

    while (-not $service.HasExited) {
        Start-Sleep -Milliseconds 500
    }
    $exitCode = Get-ProcessExitCode $service
    Set-WindowTitle 'ImageView 已停止'
    Write-Host ''
    if (($null -eq $exitCode) -or ($exitCode -eq 0)) {
        Write-Good '服务已停止。'
    } else {
        Write-Bad ("服务异常退出（退出码 {0}），请查看上方日志。" -f $exitCode)
        exit $script:ExitFail
    }

    exit $script:ExitOk
} catch {
    Write-Host ''
    Write-Bad ("[启动失败] 未预期的错误：{0}" -f $_.Exception.Message)
    if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
        Write-Detail $_.InvocationInfo.PositionMessage
    }
    Write-Host '    排查提示见 docs/DEPLOYMENT.md 的「故障排查」一节。' -ForegroundColor DarkGray
    exit $script:ExitFail
}
