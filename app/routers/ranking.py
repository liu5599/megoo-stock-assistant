"""
选股排名 API 路由
"""
from fastapi import APIRouter, Query

from app.dependencies import get_fetcher, get_raw_fetcher, get_config
from app.services.ranking_service import RankingService

router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("/run")
async def run_ranking(
    pool: str = Query("popular", description="股票池: popular/watchlist/hs300/zz500/sz50/all"),
    tech_weight: float = Query(0.40, ge=0, le=1, description="技术面权重"),
    fund_weight: float = Query(0.60, ge=0, le=1, description="基本面权重"),
    top_n: int = Query(20, ge=5, le=100, description="返回前N只"),
    normalization: str = Query("rank", description="标准化方法: rank/zscore/minmax"),
    tech_factors: str = Query("momentum,volatility,volume_corr", description="技术因子列表"),
    fund_factors: str = Query("pe,roe,revenue", description="基本面因子列表"),
    tech_weights: str = Query("", description='技术因子权重JSON，如 {"momentum":35,"volatility":30}'),
    fund_weights: str = Query("", description='基本面因子权重JSON'),
    filters: str = Query("", description="JSON格式筛选条件"),
):
    """运行多因子排名（异步执行，返回任务ID）"""
    import json
    filter_dict = {}
    if filters:
        try:
            filter_dict = json.loads(filters)
        except Exception:
            pass

    service = RankingService(get_fetcher(), get_raw_fetcher(), get_config())
    task_id = await service.start_ranking(
        pool=pool,
        tech_weight=tech_weight,
        fund_weight=fund_weight,
        top_n=top_n,
        normalization=normalization,
        tech_factors=tech_factors,
        fund_factors=fund_factors,
        tech_weights=tech_weights,
        fund_weights=fund_weights,
        filters=filter_dict,
    )
    return {"task_id": task_id, "status": "running"}


@router.get("/status/{task_id}")
async def ranking_status(task_id: str):
    """查询排名计算进度"""
    service = RankingService.instance()
    if service is None:
        return {"status": "not_found", "message": "尚无运行中的排名任务"}
    status = service.get_task_status(task_id)
    if not status:
        return {"status": "not_found", "message": "任务不存在或已过期"}
    return status


@router.get("/results/{task_id}")
async def ranking_results(task_id: str):
    """获取排名结果"""
    service = RankingService.instance()
    if service is None:
        return {"status": "not_found", "message": "尚无运行中的排名任务"}
    return service.get_results(task_id)
