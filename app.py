#!/usr/bin/env python3
"""
megoo股票助手 Web App 入口
===========================
启动 FastAPI 服务器，提供 Web 界面。
使用方法:
    python3 app.py
    python3 app.py --port 8080 --reload
"""
import sys
import os
import argparse

# 加载项目根 .env（stdlib loader；不覆盖已存在的环境变量）
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                if _k and _k not in os.environ:
                    os.environ[_k] = _v

# 将项目根目录加入Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置SSL证书：合并系统根证书，解决本机SSL拦截(自签名证书)导致的
# akshare/东财/乐咕 SSL_CERTIFICATE_VERIFY_FAILED 问题
from utils.ssl_setup import setup_ssl
setup_ssl()

# 抑制警告
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from app.main import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="megoo股票助手 Web App")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8010, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  🐂 megoo股票助手 v2.0 — Web App                           ║
║                                                            ║
║  打开浏览器访问: http://localhost:{args.port}                  ║
║  API 文档:      http://localhost:{args.port}/docs           ║
║                                                            ║
║  按 Ctrl+C 停止服务                                         ║
╚══════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
