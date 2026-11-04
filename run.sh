#!/usr/bin/env bash
# Linux / macOS 启动脚本：依赖由 uv 管理
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv。先安装（任选其一）：" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "  python3 -m pip install uv" >&2
  exit 1
fi

# uv run 会按 pyproject.toml / uv.lock 自动创建 .venv 并补齐依赖
exec uv run python -m app
