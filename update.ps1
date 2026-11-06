# ============================================================
#  ImageView 一键更新（Windows PowerShell 5.1 / 7 通用）
#
#  入口：双击 update.bat；也可以在本目录执行 .\update.ps1
#
#  流程：检查 git / origin / 工作区干净
#        → git fetch → git pull --ff-only（已最新会明确提示）
#        → uv sync → 停止属于本项目的旧服务 → 通过 start.bat 新窗口重启
#
#  安全：只更新代码，不碰 data/、config.json 和用户图片。
#        停止进程只接受「本项目目录 + python -m app + 配置端口」三者都能
#        对应上的进程；端口被其它程序占用时中止更新，不做任何停止操作。
#
#  编码：本文件必须保存为「UTF-8 with BOM + CRLF」。
# ============================================================

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$script:ProjectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$script:ReadyTimeoutSec = 90
$script:ExitOk = 0
$script:ExitFail = 1
$script:UvExe = $null
$script:UvPrefix = @()
$script:GitExe = $null

# 与 run.ps1 相同：中文输出统一按 UTF-8，避免 PowerShell 5.1 下乱码。
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
    Write-Bad "[更新失败] $Text"
    Write-Host '    排查提示见 docs/DEPLOYMENT.md 的「故障排查」一节。' -ForegroundColor DarkGray
    exit $script:ExitFail
}

function Set-WindowTitle([string]$Text) {
    try { $Host.UI.RawUI.WindowTitle = $Text } catch { }
}

# ------------------------------------------------------------
#  git 封装
# ------------------------------------------------------------

function Find-GitCommand {
    $cmd = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $cmd) { return $false }
    $exe = [string]$cmd.Path
    if (-not $exe) { $exe = [string]$cmd.Source }
    if ([string]::IsNullOrWhiteSpace($exe)) { return $false }
    $script:GitExe = $exe
    return $true
}

function Invoke-Git([string[]]$GitArgs) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $script:GitExe @GitArgs 2>&1 | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $saved
    }
    return [pscustomobject]@{ ExitCode = $code; Output = $lines }
}

function Invoke-GitLive([string[]]$GitArgs) {
    & $script:GitExe @GitArgs | Out-Host
    return $LASTEXITCODE
}

function Get-GitText([string[]]$GitArgs) {
    $result = Invoke-Git $GitArgs
    if ($result.ExitCode -ne 0) { return $null }
    return (($result.Output -join ' ').Trim())
}

# ------------------------------------------------------------
#  uv 定位（更新流程不重复做自动安装交互）
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
            if (Test-UvCandidate ([string]$file.FullName) @()) {
                $script:UvExe = [string]$file.FullName
                $script:UvPrefix = @()
                return $true
            }
        }
    }
    $pythons = @()
    $pyCmd = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pyCmd) { $pythons += ([string]$pyCmd.Path) }
    $pyLauncher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pyLauncher) { $pythons += ([string]$pyLauncher.Path) }
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

function Invoke-UvCommand([string[]]$UvArgs) {
    $all = @($script:UvPrefix) + @($UvArgs)
    & $script:UvExe @all | Out-Host
    return $LASTEXITCODE
}

# ------------------------------------------------------------
#  配置 / 端口 / 进程
# ------------------------------------------------------------

function Get-ConfigPath {
    if (-not [string]::IsNullOrWhiteSpace($env:IR_CONFIG)) { return $env:IR_CONFIG }
    return (Join-Path $script:ProjectRoot 'config.json')
}

function Read-AppConfig {
    $result = [pscustomobject]@{ Host = '0.0.0.0'; Port = 17900; Path = (Get-ConfigPath); Exists = $false }
    if (-not (Test-Path -LiteralPath $result.Path)) { return $result }
    $result.Exists = $true
    try {
        $text = [System.IO.File]::ReadAllText($result.Path, [System.Text.Encoding]::UTF8)
        $obj = $text | ConvertFrom-Json
    } catch {
        Write-Note ("config.json 解析失败（{0}），将使用默认端口。" -f $_.Exception.Message)
        return $result
    }
    if ($obj -isnot [System.Management.Automation.PSCustomObject]) {
        Write-Note 'config.json 顶层不是 JSON 对象，将使用默认端口。'
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
    return $result
}

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
            Id             = [int]$p.ProcessId
            ParentId       = [int]$p.ParentProcessId
            Name           = [string]$p.Name
            ExecutablePath = [string]$p.ExecutablePath
            CommandLine    = [string]$p.CommandLine
        }
    } catch {
        return $null
    }
}

function Get-ProcessChain([int]$ProcessId) {
    $chain = @()
    $current = $ProcessId
    for ($i = 0; $i -lt 8; $i++) {
        if ($current -le 0) { break }
        $snapshot = Get-ProcessSnapshot $current
        if ($null -eq $snapshot) { break }
        $chain += $snapshot
        if ($snapshot.ParentId -eq $current) { break }
        $current = [int]$snapshot.ParentId
    }
    return $chain
}

function Test-ProjectServiceChain([object]$Chain) {
    # 判定标准：监听端口的是 `python -m app`，且进程链里能对应上本项目目录。
    # uv 在 Windows 上会再拉起一个基础解释器进程，所以不能只看监听进程本身。
    $items = @($Chain)
    if ($items.Count -eq 0) { return $false }
    $listener = $items[0]
    if (([string]$listener.CommandLine) -notmatch '(^|\s)-m\s+app(\s|$)') { return $false }
    foreach ($item in $items) {
        $exe = [string]$item.ExecutablePath
        if ((-not [string]::IsNullOrWhiteSpace($exe)) -and
            $exe.StartsWith($script:ProjectRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
        $cmd = [string]$item.CommandLine
        if ((-not [string]::IsNullOrWhiteSpace($cmd)) -and
            ($cmd.IndexOf($script:ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)) {
            return $true
        }
    }
    return $false
}

function Stop-ProjectService([int]$ListenerPid, [int]$Port) {
    $chain = @(Get-ProcessChain $ListenerPid)
    $launcherNames = @('cmd.exe', 'powershell.exe', 'pwsh.exe', 'uv.exe')
    $target = $null
    # 优先结束最高的「本项目的启动器」进程，连控制台窗口一起收掉；
    # 如果服务是在用户已有的终端里手工启动的，就停到 run.ps1/uv 为止，不动那个终端。
    foreach ($item in $chain) {
        $name = ([string]$item.Name).ToLowerInvariant()
        $cmd = [string]$item.CommandLine
        if (($launcherNames -contains $name) -and (-not [string]::IsNullOrWhiteSpace($cmd)) -and
            ($cmd.IndexOf($script:ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)) {
            $target = $item
        }
    }
    if ($null -eq $target) {
        foreach ($item in $chain) {
            if (([string]$item.Name) -ieq 'uv.exe') { $target = $item; break }
        }
    }
    if ($null -eq $target) { $target = $chain[0] }

    Write-Detail ("停止进程树：PID {0}（{1}）" -f $target.Id, $target.Name)
    & taskkill.exe /PID $target.Id /T /F 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Note '未能结束整棵进程树，改为直接结束监听进程。'
        Stop-Process -Id $ListenerPid -Force -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if ((Get-ListenerProcessId $Port) -eq 0) { return $true }
    }
    return $false
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
#  主流程
# ------------------------------------------------------------

try {
    Write-Host ''
    Write-Host '==============================================' -ForegroundColor DarkCyan
    Write-Host '  ImageView 一键更新' -ForegroundColor Cyan
    Write-Host ("  项目目录：{0}" -f $script:ProjectRoot) -ForegroundColor DarkGray
    Write-Host '==============================================' -ForegroundColor DarkCyan

    Set-WindowTitle 'ImageView 更新中'

    # ---------- 1. 环境检查 ----------

    Write-Step '检查运行环境'
    if (-not (Find-GitCommand)) {
        Stop-WithError '未找到 git。更新功能只适用于 git clone 得到的目录，请先安装 Git（https://git-scm.com/download/win）。'
    }
    Write-Good ("git：{0}" -f $script:GitExe)

    if (-not (Find-UvCommand)) {
        Write-Bad '未找到 uv。'
        Write-Detail '请先双击 start.bat，它会引导安装 uv；装好后重新双击 update.bat。'
        Stop-WithError '缺少 uv，无法同步依赖。'
    }
    $uvDesc = $script:UvExe
    if ($script:UvPrefix.Count -gt 0) { $uvDesc = ('{0} -m uv' -f $script:UvExe) }
    Write-Good ("uv：{0}" -f $uvDesc)

    # ---------- 2. git 仓库检查 ----------

    Write-Step '检查 git 仓库'
    $inside = Invoke-Git @('rev-parse', '--is-inside-work-tree')
    if (($inside.ExitCode -ne 0) -or (($inside.Output -join '').Trim() -ne 'true')) {
        Stop-WithError ("当前目录不是 git 工作区：{0}" -f $script:ProjectRoot)
    }
    $top = Get-GitText @('rev-parse', '--show-toplevel')
    if ($null -eq $top) {
        Stop-WithError '无法读取 git 仓库根目录。'
    }
    $topPath = [System.IO.Path]::GetFullPath($top).TrimEnd('\')
    if (-not $topPath.Equals($script:ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-WithError ("update.ps1 必须放在仓库根目录运行（仓库根目录：{0}）。" -f $topPath)
    }
    Write-Good ("仓库：{0}" -f $topPath)

    $originUrl = Get-GitText @('remote', 'get-url', 'origin')
    if ($null -eq $originUrl) {
        Stop-WithError '当前仓库没有名为 origin 的远程仓库，无法更新。请先执行：git remote add origin <仓库地址>'
    }
    Write-Good ("origin：{0}" -f $originUrl)

    $branch = Get-GitText @('symbolic-ref', '--short', '-q', 'HEAD')
    if ($null -eq $branch) {
        Stop-WithError '当前处于分离 HEAD（detached HEAD）状态，无法安全更新。请先切回分支：git switch main'
    }
    Write-Good ("当前分支：{0}" -f $branch)

    $status = Invoke-Git @('status', '--porcelain')
    if ($status.ExitCode -ne 0) {
        Stop-WithError '无法读取 git 工作区状态。'
    }
    $dirty = @($status.Output | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    if ($dirty.Count -gt 0) {
        Write-Bad ("工作区有 {0} 项未提交的改动，已中止更新（不会丢弃你的改动）：" -f $dirty.Count)
        $showCount = [Math]::Min(10, $dirty.Count)
        for ($i = 0; $i -lt $showCount; $i++) { Write-Detail ([string]$dirty[$i]) }
        if ($dirty.Count -gt $showCount) { Write-Detail '...' }
        Stop-WithError '请先提交、暂存（git stash）或撤销这些改动，再双击 update.bat。'
    }
    Write-Good '工作区干净。'

    # ---------- 3. 拉取更新 ----------

    Write-Step ("从 origin 获取最新代码（git fetch）")
    $fetchCode = Invoke-GitLive @('fetch', 'origin', '--prune')
    if ($fetchCode -ne 0) {
        Stop-WithError ("git fetch 失败（退出码 {0}）。请检查网络、代理或 git 凭据后重试。" -f $fetchCode)
    }

    $remoteRef = ('origin/{0}' -f $branch)
    $remoteHead = Get-GitText @('rev-parse', '--verify', '--quiet', ('refs/remotes/' + $remoteRef))
    if ($null -eq $remoteHead) {
        Stop-WithError ("远程仓库没有分支 {0}（origin 上可能改了默认分支）。" -f $branch)
    }

    $oldHead = Get-GitText @('rev-parse', 'HEAD')
    if ($null -eq $oldHead) {
        Stop-WithError '无法读取当前提交。'
    }
    $counts = Get-GitText @('rev-list', '--left-right', '--count', ('HEAD...{0}' -f $remoteRef))
    if ($null -eq $counts) {
        Stop-WithError '无法比较本地与远程的提交差异。'
    }
    $parts = @($counts -split '\s+' | Where-Object { $_ -ne '' })
    $ahead = 0
    $behind = 0
    if ($parts.Count -ge 2) {
        $ahead = [int]$parts[0]
        $behind = [int]$parts[1]
    }
    $shortOld = $oldHead.Substring(0, [Math]::Min(7, $oldHead.Length))

    if (($behind -eq 0) -and ($ahead -eq 0)) {
        Write-Good ("已是最新版本（{0} @ {1}），无需拉取。" -f $branch, $shortOld)
    } elseif (($ahead -gt 0) -and ($behind -gt 0)) {
        Stop-WithError ("本地分支与 {0} 已分叉（本地领先 {1} 个提交，落后 {2} 个）。请先手动处理：git pull 或 git rebase。" -f $remoteRef, $ahead, $behind)
    } elseif ($ahead -gt 0) {
        Write-Note ("本地比远程多 {0} 个提交，不需要拉取；继续同步依赖并重启服务。" -f $ahead)
    } else {
        Write-Detail ("发现 {0} 个新提交，执行 git pull --ff-only ..." -f $behind)
        $pullCode = Invoke-GitLive @('pull', '--ff-only')
        if ($pullCode -ne 0) {
            Stop-WithError ("git pull --ff-only 失败（退出码 {0}）。请检查网络/凭据；本地与远程可能已分叉，可手动执行 git pull 查看原因。" -f $pullCode)
        }
        $newHead = Get-GitText @('rev-parse', 'HEAD')
        $shortNew = $shortOld
        if ($newHead) { $shortNew = $newHead.Substring(0, [Math]::Min(7, $newHead.Length)) }
        Write-Good ("代码已更新：{0} → {1}" -f $shortOld, $shortNew)
        $logLines = @((Invoke-Git @('log', '--oneline', '--no-decorate', ('{0}..HEAD' -f $oldHead))).Output)
        foreach ($line in $logLines) {
            if (-not [string]::IsNullOrWhiteSpace([string]$line)) { Write-Detail ([string]$line) }
        }
    }

    # ---------- 4. 同步依赖 ----------

    Write-Step '同步依赖（uv sync）'
    $syncCode = Invoke-UvCommand @('sync')
    if ($syncCode -ne 0) {
        Stop-WithError ("uv sync 失败（退出码 {0}）。代码可能已更新，但依赖没同步；请检查网络后重试。" -f $syncCode)
    }
    Write-Good '依赖已同步。'

    # ---------- 5. 停止旧服务 ----------

    Write-Step '停止正在运行的旧服务'
    $config = Read-AppConfig
    $probeHost = Get-ProbeHost $config.Host
    $url = (Format-Url $probeHost $config.Port)
    $configDesc = $config.Path
    if (-not $config.Exists) { $configDesc = $configDesc + '（不存在，用默认配置）' }
    Write-Detail ("配置文件：{0}" -f $configDesc)
    Write-Detail ("服务端口：{0}" -f $config.Port)

    $listenerPid = Get-ListenerProcessId $config.Port
    if ($listenerPid -eq 0) {
        Write-Good '端口没有监听进程，未检测到运行中的服务，跳过停止步骤。'
    } else {
        $chain = @(Get-ProcessChain $listenerPid)
        if (-not (Test-ProjectServiceChain $chain)) {
            Write-Bad ("端口 {0} 已被其他程序占用，且无法确认它是本项目的服务：" -f $config.Port)
            Show-PortOwnerHint $config.Port
            Stop-WithError ("已中止更新，没有停止任何进程。请关闭占用端口 {0} 的程序，或修改 config.json 里的 port 后重试。" -f $config.Port)
        }
        Write-Detail ("检测到本项目服务：PID {0}（python -m app，端口 {1}）" -f $listenerPid, $config.Port)
        if (-not (Stop-ProjectService $listenerPid $config.Port)) {
            Stop-WithError ("旧服务停止超时，端口 {0} 仍被占用。" -f $config.Port)
        }
        Write-Good '旧服务已停止。'
    }

    # ---------- 6. 新窗口重启 ----------

    Write-Step '通过 start.bat 在新窗口启动服务'
    $startBat = Join-Path $script:ProjectRoot 'start.bat'
    if (-not (Test-Path -LiteralPath $startBat)) {
        Stop-WithError ("找不到 start.bat：{0}" -f $startBat)
    }
    try {
        Start-Process -FilePath $startBat -WorkingDirectory $script:ProjectRoot -ErrorAction Stop
    } catch {
        Stop-WithError ("无法启动新的服务窗口：{0}" -f $_.Exception.Message)
    }
    Write-Detail '已打开新的服务窗口，等待服务就绪 ...'

    $ready = $false
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $script:ReadyTimeoutSec) {
        if (Test-ImageViewAt $probeHost $config.Port) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        Stop-WithError ("代码已更新，但新服务在 {0} 秒内没有就绪。请查看新打开窗口中的日志。" -f $script:ReadyTimeoutSec)
    }

    Write-Host ''
    Write-Good '更新完成，服务已在新窗口运行。'
    Write-Detail ("访问地址：{0}" -f $url)
    Write-Detail '更新过程不会改动 data/、config.json 和图片文件。'
    Set-WindowTitle 'ImageView 已更新'
    exit $script:ExitOk
} catch {
    Write-Host ''
    Write-Bad ("[更新失败] 未预期的错误：{0}" -f $_.Exception.Message)
    if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
        Write-Detail $_.InvocationInfo.PositionMessage
    }
    Write-Host '    排查提示见 docs/DEPLOYMENT.md 的「故障排查」一节。' -ForegroundColor DarkGray
    exit $script:ExitFail
}
