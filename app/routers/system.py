"""
系统 API 路由
"""
import time
from fastapi import APIRouter, Query

from app.dependencies import get_cache, get_config

router = APIRouter(prefix="/system", tags=["system"])

_start_time = time.time()


@router.get("/status")
async def system_status():
    """获取系统状态"""
    cache = get_cache()
    stats = cache.get_stats() if cache else {}

    # 动态获取当前数据源类型
    try:
        from app.dependencies import get_raw_fetcher
        fetcher = get_raw_fetcher()
        data_source = type(fetcher).__name__
    except Exception:
        data_source = "unknown"

    return {
        "data_source": data_source,
        "cache_stats": stats,
        "uptime_seconds": int(time.time() - _start_time),
        "version": "2.0.0",
    }


@router.post("/cache/clear")
async def clear_cache(
    data_type: str = Query("all", description="缓存类型: all/kline/financial/quote"),
):
    """清除缓存"""
    cache = get_cache()
    if data_type == "all":
        cache.cleanup_expired()
        cache.invalidate(None)
        return {"message": "所有过期缓存已清理"}
    else:
        cache.invalidate(data_type)
        return {"message": f"{data_type} 缓存已清理"}
