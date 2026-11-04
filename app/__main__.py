"""python -m app：读 config.json 并用 uvicorn 启动服务。"""

import socket

import uvicorn

from .main import create_app
from .settings import load_config


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    cfg = load_config()
    app = create_app()
    print(f"ImageRating 启动中：http://127.0.0.1:{cfg['port']}")
    if str(cfg["host"]) == "0.0.0.0":
        print(f"同网段其他设备访问：http://{_lan_ip()}:{cfg['port']}")
    uvicorn.run(app, host=str(cfg["host"]), port=int(cfg["port"]), log_level="info")


if __name__ == "__main__":
    main()
