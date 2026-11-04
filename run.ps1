# 在 ComfyUI 主机上启动 ImageRating（Windows PowerShell，依赖由 uv 管理）
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host '未找到 uv。先安装（任选其一）：' -ForegroundColor Yellow
    Write-Host '  python -m pip install uv'
    Write-Host '  winget install astral-sh.uv'
    exit 1
}

# uv run 会自动按 pyproject.toml / uv.lock 创建 .venv 并补齐依赖
uv run python -m app
