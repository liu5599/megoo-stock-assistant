"""
短线选股 API — 指南针风格三把锁体系
"""
import uuid
import traceback
import asyncio
from fastapi import APIRouter, Query

from app.dependencies import get_fetcher, get_raw_fetcher
from utils.logger import logger
from utils.task_store import load_tasks, save_tasks

router = APIRouter(prefix="/screener", tags=["screener"])

_tasks: dict = load_tasks("screener")


def _persist_tasks():
    save_tasks("screener", _tasks)


@router.get("/surge")
async def run_surge(
    pool: str = Query("popular"),
    top_n: int = Query(10, ge=3, le=50),
    period: str = Query("T+3", description="T+1 / T+3 / 波段 / 长线"),
):
    """指南针风格三把锁选股"""
    task_id = uuid.uuid4().hex[:8]
    _tasks[task_id] = {"status": "running", "progress": 0, "step": "初始化..."}

    async def _run():
        try:
            from engine.short_term_screener import CompassScreener
            from data.data_utils import fetch_batch_kline_with_cache

            _tasks[task_id].update({"progress": 2, "step": "获取大盘数据..."})
            fetcher = get_fetcher()
            screener = CompassScreener()

            # 大盘判断
            try:
                sentiment = fetcher.get_market_sentiment()
                market = screener.judge_market(sentiment)
            except Exception:
                market = {"status": "未知", "heat": 50, "position_pct": 30}

            _tasks[task_id].update({"progress": 5, "step": "构建股票池..."})
            pool_map = {"hs300": "000300", "zz500": "000905", "sz50": "000016"}
            if pool in pool_map:
                try:
                    codes = fetcher.get_index_components(pool_map[pool]) or []
                except Exception:
                    codes = []
                if not codes or len(codes) < 20:
                    from config.stock_lists import POPULAR_STOCKS
                    codes = [s["code"] for s in POPULAR_STOCKS]
            else:
                from config.stock_lists import POPULAR_STOCKS
                codes = [s["code"] for s in POPULAR_STOCKS]

            _tasks[task_id].update({"progress": 10, "step": f"获取K线({len(codes)}只)..."})
            kline_data = fetch_batch_kline_with_cache(fetcher, codes, days=120)

            name_map = {}
            for code in list(kline_data.keys()):
                try:
                    name_map[code] = fetcher.get_stock_name(code) or code
                except Exception:
                    name_map[code] = code

            _tasks[task_id].update({"progress": 60, "step": f"三把锁扫描({period})..."})
            signals = screener.screen(kline_data, name_map, period=period, top_n=top_n)

            results = []
            for s in signals:
                results.append({
                    "code": s.code, "name": s.name, "price": s.price,
                    "period": s.period,
                    "capital_score": s.capital_score,
                    "trend_score": s.trend_score,
                    "signal_score": s.signal_score,
                    "total_score": s.total_score,
                    "reasons": s.reasons,
                    "buy_price": s.buy_price,
                    "stop_loss": s.stop_loss,
                    "target_1": s.target_1,
                    "target_2": s.target_2,
                    "action": s.action,
                    "confidence": s.confidence,
                    "position_pct": s.position_pct,
                    "hold_days": s.hold_days,
                    "stop_pct": round((s.price - s.stop_loss) / s.price * 100, 2),
                    "gain_pct": round((s.target_1 / s.price - 1) * 100, 2),
                })

            _tasks[task_id].update({
                "status": "done", "progress": 100, "step": "完成",
                "results": results, "total": len(results),
                "market": market,
            })
            _persist_tasks()
        except Exception as e:
            logger.error(f"surge错误: {e}\n{traceback.format_exc()}")
            _tasks[task_id].update({"status": "error", "step": "失败", "error": str(e)})
            _persist_tasks()

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "running"}


@router.get("/surge/status/{task_id}")
async def surge_status(task_id: str):
    t = _tasks.get(task_id)
    if not t:
        return {"status": "not_found", "message": "任务不存在"}
    return t


@router.get("/surge/results/{task_id}")
async def surge_results(task_id: str):
    t = _tasks.get(task_id)
    if not t:
        return {"status": "not_found"}
    return t
