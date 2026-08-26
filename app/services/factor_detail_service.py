"""
因子详情服务 — 第三/四层下钻
============================
第三层「因子历史时序」：某只股票某个技术因子过去一段时间的变化曲线。
第四层「分行业对比」：某只股票某个技术因子在同行业股票中的分位。

只支持技术因子（基于 K线，腾讯源稳定可算）；基本面因子需历史财务数据，
东财限频期间拿不到，暂不提供。
"""
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from utils.logger import logger


# 技术因子名（支持第三/四层下钻的因子）
TECH_FACTORS = {
    "momentum_20": "20日动量",
    "volatility_20": "低波动率",
    "volume_price_corr": "量价配合",
    "reversal_5": "5日反转",
    "rsi_14": "RSI(14)",
    "turnover_20": "换手率",
}


def _factor_series(df: pd.DataFrame, factor: str) -> pd.Series:
    """对单只股票的K线 df，计算某因子的完整时序（index 对齐 df.index）"""
    close = df["close"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else None
    idx = df.index

    if factor == "momentum_20":
        return close.pct_change(20) * 100
    if factor == "volatility_20":
        return close.pct_change().rolling(20).std() * np.sqrt(252) * 100
    if factor == "volume_price_corr":
        if volume is None:
            return pd.Series(np.nan, index=idx)
        return close.pct_change().rolling(20).corr(volume.pct_change())
    if factor == "reversal_5":
        return -close.pct_change(5) * 100
    if factor == "rsi_14":
        from analysis.indicators import compute_rsi
        return compute_rsi(close, 14).reindex(idx)
    if factor == "turnover_20":
        src = df["turnover"].astype(float) if "turnover" in df.columns else volume
        return src.rolling(20).mean() if src is not None else pd.Series(np.nan, index=idx)
    return pd.Series(np.nan, index=idx)


def _factor_current(df: pd.DataFrame, factor: str) -> Optional[float]:
    """某因子的当前值（最后一个有效值）"""
    s = _factor_series(df, factor).dropna()
    return float(s.iloc[-1]) if len(s) else None


class FactorDetailService:
    """因子详情（第三/四层下钻）"""

    def __init__(self, fetcher):
        self.fetcher = fetcher

    def factor_history(self, code: str, factor: str, days: int = 120) -> Dict:
        """第三层：因子历史时序"""
        if factor not in TECH_FACTORS:
            return {"code": code, "factor": factor, "error": f"不支持的因子（仅支持技术因子）"}

        start = time.strftime("%Y%m%d", time.localtime(time.time() - 600 * 86400))
        end = time.strftime("%Y%m%d")
        kl = self.fetcher.get_history_kline(code, "daily", start, end, "qfq")
        if kl is None or kl.df.empty:
            return {"code": code, "factor": factor, "error": "K线数据不足"}

        df = kl.df.copy().sort_values("date")
        series = _factor_series(df, factor)
        tail = series.tail(days)
        dates = [str(d)[:10] for d in df["date"].tail(days)]
        values = [None if pd.isna(v) else round(float(v), 4) for v in tail]

        return {
            "code": code,
            "name": getattr(kl, "name", "") or code,
            "factor": factor,
            "label": TECH_FACTORS.get(factor, factor),
            "dates": dates,
            "values": values,
        }

    def factor_peer(self, code: str, factor: str) -> Dict:
        """第四层：同行业因子对比 + 分位"""
        if factor not in TECH_FACTORS:
            return {"code": code, "factor": factor, "error": f"不支持的因子（仅支持技术因子）"}

        from config.stock_lists import POPULAR_STOCKS

        sector = ""
        for s in POPULAR_STOCKS:
            if s["code"] == code:
                sector = s.get("sector", "")
                break
        if not sector:
            return {"code": code, "factor": factor, "error": "该股不在内置行业池中，无法对比"}

        peers = [s for s in POPULAR_STOCKS if s.get("sector") == sector]
        if len(peers) < 2:
            return {"code": code, "factor": factor, "sector": sector, "error": "同行业样本不足"}

        from data.data_utils import fetch_stock_data
        kline_data = fetch_stock_data(self.fetcher, [s["code"] for s in peers], days=120)

        results = []
        for s in peers:
            c = s["code"]
            df = kline_data.get(c)
            if df is None or df.empty or "close" not in df.columns:
                continue
            v = _factor_current(df, factor)
            if v is None:
                continue
            results.append({"code": c, "name": s.get("name", c), "value": round(v, 4)})

        if not results:
            return {"code": code, "factor": factor, "sector": sector, "error": "同行业数据获取失败"}

        mine = next((r for r in results if r["code"] == code), None)
        if mine is None:
            return {"code": code, "factor": factor, "sector": sector, "error": "该股无有效数据"}

        values = [r["value"] for r in results]
        below = sum(1 for v in values if v < mine["value"])
        percentile = round(below / len(values) * 100, 1)

        return {
            "code": code,
            "factor": factor,
            "label": TECH_FACTORS.get(factor, factor),
            "sector": sector,
            "value": mine["value"],
            "percentile": percentile,
            "peers": results,
        }
