"""部署配置：只放 host / port / data_dir。

密码哈希、图片根目录、会话密钥都是可运行时修改的数据，存在 SQLite 的 settings 表里。
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {"host": "0.0.0.0", "port": 17900, "data_dir": "data"}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    path = Path(os.environ.get("IR_CONFIG") or PROJECT_ROOT / "config.json")
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            cfg.update(loaded)
    data_dir = Path(cfg["data_dir"])
    cfg["data_dir"] = str(data_dir if data_dir.is_absolute() else PROJECT_ROOT / data_dir)
    return cfg


def web_dir() -> Path:
    return PROJECT_ROOT / "web"
