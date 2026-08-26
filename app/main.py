"""
FastAPI 应用创建和配置
"""
import os
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 模板路径
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    from app.dependencies import get_cache, get_fetcher
    from utils.logger import setup_logger, logger
    setup_logger("INFO")
    logger.info("🚀 megoo股票助手 Web App 启动中...")
    logger.info(f"   模板目录: {TEMPLATE_DIR}")
    logger.info(f"   静态目录: {STATIC_DIR}")

    # 清理过期缓存
    cache = get_cache()
    cache.cleanup_expired()
    logger.info(f"   缓存已就绪")

    # 后台预热操盘台数据（不阻塞启动，用户打开时秒出数据）
    import threading

    def _load_persisted_overview():
        """启动时载入上次持久化的 overview（标记为已过期 → SWR 秒回旧值+后台刷新）"""
        try:
            import json as _json
            from pathlib import Path as _Path
            from analysis import _cache
            _p = _Path(__file__).parent.parent.parent / "cache_data" / "ops_overview.json"
            if _p.exists():
                data = _json.loads(_p.read_text(encoding="utf-8"))
                # 存为"已过期"状态：访问时 SWR 立即返回旧值并后台刷新
                _cache._CACHE[("ops_overview_persist", "", "")] = (time.time() - 999999, data)
                logger.info(f"📦 已载入持久化盘面数据（{_p.name}）")
        except Exception as e:
            logger.warning(f"载入持久化盘面数据失败: {e}")

    def _warmup():
        try:
            from app.routers.ops import ops_overview
            ops_overview()
            logger.info("🔥 操盘台数据预热完成")
        except Exception as e:
            logger.warning(f"操盘台预热失败: {e}")

    _load_persisted_overview()
    threading.Thread(target=_warmup, daemon=True).start()

    yield

    # 关闭时
    logger.info("👋 megoo股票助手 Web App 关闭")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="megoo股票助手",
        description="沪深A股多因子选股框架 Web 应用",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ===== 统一异常处理器 =====
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        from utils.logger import logger
        logger.error(f"未捕获异常: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "服务器内部错误", "detail": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=422,
            content={"error": "参数错误", "detail": str(exc)},
        )

    # ===== 简单的并发任务限制 =====
    _active_tasks = {"ranking": 0, "backtest": 0}
    _max_concurrent = {"ranking": 3, "backtest": 3}

    @app.middleware("http")
    async def task_limit_middleware(request: Request, call_next):
        """限制同时运行的排名/回测任务数"""
        path = request.url.path
        for task_type in ("ranking", "backtest"):
            if f"/api/{task_type}/run" in path and request.method in ("GET", "POST"):
                if _active_tasks[task_type] >= _max_concurrent[task_type]:
                    return JSONResponse(
                        status_code=429,
                        content={"error": f"已有 {_active_tasks[task_type]} 个{task_type}任务在运行，请稍后再试"},
                    )
                _active_tasks[task_type] += 1
                try:
                    response = await call_next(request)
                finally:
                    _active_tasks[task_type] -= 1
                return response
        return await call_next(request)

    # 静态文件
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # 注册路由
    from app.routers import stock, ranking, backtest, watchlist, system, pages, market, screener, ops
    app.include_router(stock.router, prefix="/api")
    app.include_router(ranking.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(watchlist.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    app.include_router(market.router, prefix="/api")
    app.include_router(screener.router, prefix="/api")
    app.include_router(ops.router, prefix="/api")
    app.include_router(pages.router)

    return app
