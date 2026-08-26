"""
市场数据 API 路由
"""
from fastapi import APIRouter, Query

from app.dependencies import get_raw_fetcher
from app.services.market_service import MarketService

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview")
async def market_overview():
    """获取市场总览（指数+行业+涨跌统计）"""
    svc = MarketService(get_raw_fetcher())
    return await svc.get_market_overview()


@router.get("/sectors")
async def hot_sectors(limit: int = Query(15, description="返回行业数")):
    """获取行业板块热度排名"""
    svc = MarketService(get_raw_fetcher())
    return await svc.get_hot_sectors(limit)
