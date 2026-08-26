"""
回测 API 路由
"""
from fastapi import APIRouter, Query

from app.dependencies import get_fetcher, get_raw_fetcher, get_config
from app.services.backtest_service import BacktestService

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run")
async def run_backtest(
    start_date: str = Query("20250101", description="开始日期 YYYYMMDD"),
    end_date: str = Query("20260624", description="结束日期 YYYYMMDD"),
    pool: str = Query("popular", description="股票池"),
    rebalance_freq: str = Query("monthly", description="调仓频率: daily/weekly/monthly"),
    max_positions: int = Query(20, ge=5, le=50),
    initial_capital: float = Query(1_000_000, ge=100_000),
    tech_weight: float = Query(0.40, ge=0, le=1),
    fund_weight: float = Query(0.60, ge=0, le=1),
):
    """启动回测（异步执行）"""
    service = BacktestService(get_fetcher(), get_raw_fetcher(), get_config())
    task_id = await service.start_backtest(
        start_date=start_date,
        end_date=end_date,
        pool=pool,
        rebalance_freq=rebalance_freq,
        max_positions=max_positions,
        initial_capital=initial_capital,
        tech_weight=tech_weight,
        fund_weight=fund_weight,
    )
    return {"task_id": task_id, "status": "running"}


@router.get("/status/{task_id}")
async def backtest_status(task_id: str):
    """查询回测进度"""
    service = BacktestService.instance()
    if service is None:
        return {"status": "not_found", "message": "尚无运行中的回测任务"}
    status = service.get_task_status(task_id)
    if not status:
        return {"status": "not_found", "message": "任务不存在或已过期"}
    return status


@router.get("/result/{task_id}")
async def backtest_result(task_id: str):
    """获取回测结果"""
    service = BacktestService.instance()
    if service is None:
        return {"status": "not_found", "message": "尚无运行中的回测任务"}
    return service.get_result(task_id)
