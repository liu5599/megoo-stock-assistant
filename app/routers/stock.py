"""
股票数据 API 路由
"""
from fastapi import APIRouter, Query, HTTPException

from app.dependencies import get_fetcher, get_raw_fetcher
from app.services.stock_service import StockService
from utils.logger import logger

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/search")
async def search_stocks(q: str = Query(..., min_length=1, description="搜索关键词")):
    """搜索股票（baostock + 东方财富双路）"""
    results = []
    # 先用 baostock 搜索
    try:
        fetcher = get_raw_fetcher()
        results = fetcher.search_stocks(q) or []
    except Exception as e:
        logger.debug(f"baostock 搜索失败 {q}: {e}")

    # 补充东方财富搜索结果
    if len(results) < 5:
        try:
            from app.dependencies import get_em_fetcher
            em = get_em_fetcher()
            em_results = em.search_stocks(q) or []
            existing = {r["code"] for r in results}
            for r in em_results:
                if r["code"] not in existing:
                    results.append(r)
        except Exception as e:
            logger.debug(f"东方财富搜索失败 {q}: {e}")

    return {"stocks": results[:20]}


@router.get("/{code}")
async def get_stock_detail(code: str):
    """获取个股综合分析"""
    service = StockService(get_fetcher(), get_raw_fetcher())
    try:
        analysis = await service.get_stock_analysis(code)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/kline")
async def get_kline_data(
    code: str,
    days: int = Query(250, ge=30, le=500, description="交易日数"),
    indicators: str = Query("ma,macd,rsi,kdj", description="需要计算的指标，逗号分隔"),
):
    """获取K线图表数据（含技术指标）"""
    service = StockService(get_fetcher(), get_raw_fetcher())
    try:
        indicator_list = [i.strip() for i in indicators.split(",") if i.strip()]
        return await service.get_kline_chart_data(code, days, indicator_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/financial")
async def get_financial(code: str):
    """获取财务数据"""
    service = StockService(get_fetcher(), get_raw_fetcher())
    try:
        return await service.get_financial_data(code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/compass")
async def get_compass_analysis(code: str):
    """获取指南针风格三把锁分析+买卖点"""
    import asyncio
    try:
        service = StockService(get_fetcher(), get_raw_fetcher())
        kline_result = await service.get_kline_data(code, days=120, indicators="ma,macd,rsi,kdj,boll")
        if not kline_result or not kline_result.get("klines"):
            raise HTTPException(status_code=404, detail="无K线数据")

        import pandas as pd
        klines = kline_result["klines"]
        df = pd.DataFrame(klines)
        df = df.rename(columns={
            "open": "open", "close": "close", "high": "high", "low": "low", "volume": "volume"
        })

        from engine.short_term_screener import CompassScreener
        screener = CompassScreener()

        periods = ["T+1", "T+3", "波段", "长线"]
        all_signals = {}
        for p in periods:
            sig = screener.evaluate(code, kline_result.get("name", code), df, p)
            if sig:
                all_signals[p] = {
                    "total_score": sig.total_score,
                    "capital_score": sig.capital_score,
                    "trend_score": sig.trend_score,
                    "signal_score": sig.signal_score,
                    "reasons": sig.reasons,
                    "buy_price": sig.buy_price,
                    "stop_loss": sig.stop_loss,
                    "target_1": sig.target_1,
                    "target_2": sig.target_2,
                    "confidence": sig.confidence,
                    "position_pct": sig.position_pct,
                    "hold_days": sig.hold_days,
                    "stop_pct": round((sig.price - sig.stop_loss) / sig.price * 100, 2),
                    "gain_pct": round((sig.target_1 / sig.price - 1) * 100, 2),
                }

        # 计算各周期指标值（不判断通过与否）
        raw_eval = {}
        for p in periods:
            cap_s, cap_r = screener._capital_lock(df, p)
            trend_s, trend_r = screener._trend_lock(df, p)
            sig_s, sig_r = screener._signal_lock(df, p)
            pts = screener.calc_trade_points(df, float(df["close"].iloc[-1]))
            raw_eval[p] = {
                "capital": {"score": cap_s, "reasons": cap_r},
                "trend": {"score": trend_s, "reasons": trend_r},
                "signal": {"score": sig_s, "reasons": sig_r},
                "points": pts,
                "total": cap_s + trend_s + sig_s,
            }

        return {
            "code": code, "name": kline_result.get("name", code),
            "price": kline_result.get("price", 0),
            "signals": all_signals,
            "raw": raw_eval,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/factor-history")
async def factor_history(code: str, factor: str = Query("momentum_20", description="技术因子名")):
    """因子历史时序（第三层下钻）"""
    import asyncio
    from app.services.factor_detail_service import FactorDetailService
    try:
        svc = FactorDetailService(get_raw_fetcher())
        return await asyncio.to_thread(svc.factor_history, code, factor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/factor-peer")
async def factor_peer(code: str, factor: str = Query("momentum_20", description="技术因子名")):
    """同行业因子对比 + 分位（第四层下钻）"""
    import asyncio
    from app.services.factor_detail_service import FactorDetailService
    try:
        svc = FactorDetailService(get_raw_fetcher())
        return await asyncio.to_thread(svc.factor_peer, code, factor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
