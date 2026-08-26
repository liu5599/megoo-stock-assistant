"""
个股分析服务 — 封装 K线获取、技术分析、图表数据组装
"""
import asyncio
from typing import List, Dict, Any
import numpy as np
import pandas as pd

from analysis.indicators import (
    compute_multi_ma, compute_macd, compute_rsi,
    compute_kdj, compute_bollinger, compute_volume_ma,
)
from analysis.technical import TechnicalAnalyzer
from data.models import KLineData
from utils.logger import logger


class StockService:
    """个股分析服务"""

    def __init__(self, fetcher, raw_fetcher):
        self.fetcher = fetcher
        self.raw_fetcher = raw_fetcher

    async def get_stock_analysis(self, code: str) -> dict:
        """获取个股综合分析（通过线程池执行同步IO）"""
        fetcher = self.fetcher
        raw = self.raw_fetcher

        def _fetch():
            name = raw.get_stock_name(code)
            kline = fetcher.get_history_kline(code, period="daily", adjust="qfq")
            financial = fetcher.get_financial_data(code)

            result = {
                "code": code,
                "name": name or code,
                "kline_available": kline is not None and not kline.df.empty,
            }

            if kline and not kline.df.empty:
                result["latest_close"] = float(kline.df["close"].iloc[-1])
                result["data_points"] = len(kline.df)
                try:
                    analyzer = TechnicalAnalyzer(kline)
                    summary = analyzer.get_technical_summary()
                    result["technical"] = {
                        "trend": summary.trend_direction,
                        "strength": summary.trend_strength,
                        "macd_signal": summary.macd_signal,
                        "rsi_value": summary.rsi_value,
                        "rsi_signal": summary.rsi_signal,
                        "kdj_signal": summary.kdj_signal,
                        "bollinger_signal": summary.bollinger_signal,
                        "volume_signal": summary.volume_signal,
                        "support": summary.support_levels if hasattr(summary, 'support_levels') else [],
                        "resistance": summary.resistance_levels if hasattr(summary, 'resistance_levels') else [],
                        "score": summary.score,
                    }
                    m = analyzer.ma  # 均线数据
                    if m is not None and not m.empty:
                        result["technical"]["ma5"] = float(m["ma5"].iloc[-1]) if "ma5" in m else None
                        result["technical"]["ma20"] = float(m["ma20"].iloc[-1]) if "ma20" in m else None
                        result["technical"]["ma60"] = float(m["ma60"].iloc[-1]) if "ma60" in m else None
                except Exception as e:
                    logger.debug(f"技术分析失败 {code}: {e}")
                    result["technical"] = {"error": str(e)}

            if financial:
                result["financial"] = {
                    "pe": financial.pe,
                    "pb": financial.pb,
                    "roe": financial.roe,
                    "revenue_growth": financial.revenue_growth,
                    "profit_growth": financial.profit_growth,
                    "gross_margin": financial.gross_margin,
                    "net_margin": financial.net_margin,
                    "debt_ratio": financial.debt_ratio,
                    "total_market_cap": financial.total_market_cap,
                }

            return result

        return await asyncio.to_thread(_fetch)

    async def get_kline_chart_data(
        self, code: str, days: int = 250, indicators: List[str] = None
    ) -> dict:
        """获取K线图表数据（含技术指标计算）"""
        if indicators is None:
            indicators = ["ma", "macd", "rsi", "kdj"]

        from datetime import datetime, timedelta

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=int(days * 1.6))).strftime("%Y%m%d")

        fetcher = self.fetcher

        def _fetch_and_compute():
            kline = fetcher.get_history_kline(
                code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq"
            )
            if not kline or kline.df.empty:
                return {"error": "无K线数据", "code": code}

            df = kline.df.copy()
            df = df.sort_values("date").tail(days)

            # 基础OHLCV
            result = {
                "code": code,
                "dates": df["date"].tolist(),
                "ohlc": {
                    "open": [round(o, 2) for o in df["open"].tolist()],
                    "high": [round(h, 2) for h in df["high"].tolist()],
                    "low": [round(l, 2) for l in df["low"].tolist()],
                    "close": [round(c, 2) for c in df["close"].tolist()],
                },
                "volume": [int(v) for v in df["volume"].fillna(0).tolist()],
            }

            close = df["close"].astype(float)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            vol = df["volume"].astype(float)

            # 计算指标
            ind = {}
            if "ma" in indicators or not indicators:
                try:
                    mas = compute_multi_ma(close, periods=[5, 10, 20, 60, 120])
                    if mas is not None:
                        ind["ma"] = {f"ma{p}": [round(v, 2) if pd.notna(v) else None
                                                  for v in mas[f"ma{p}"].tolist()]
                                     for p in [5, 10, 20, 60, 120] if f"ma{p}" in mas}
                except Exception:
                    pass

            if "macd" in indicators or not indicators:
                try:
                    macd_df = compute_macd(close)
                    if macd_df is not None:
                        ind["macd"] = {
                            "dif": [round(v, 3) if pd.notna(v) else None
                                   for v in macd_df["dif"].tolist()],
                            "dea": [round(v, 3) if pd.notna(v) else None
                                   for v in macd_df["dea"].tolist()],
                            "bar": [round(v * 2, 3) if pd.notna(v) else None
                                   for v in macd_df["macd"].tolist()],
                        }
                except Exception:
                    pass

            if "rsi" in indicators or not indicators:
                try:
                    rsi = compute_rsi(close)
                    if rsi is not None:
                        ind["rsi"] = [round(v, 1) if pd.notna(v) else None
                                     for v in rsi.tolist()]
                except Exception:
                    pass

            if "kdj" in indicators or not indicators:
                try:
                    kdj_df = compute_kdj(high, low, close)
                    if kdj_df is not None:
                        ind["kdj"] = {
                            "k": [round(v, 1) if pd.notna(v) else None
                                 for v in kdj_df["k"].tolist()],
                            "d": [round(v, 1) if pd.notna(v) else None
                                 for v in kdj_df["d"].tolist()],
                            "j": [round(v, 1) if pd.notna(v) else None
                                 for v in kdj_df["j"].tolist()],
                        }
                except Exception:
                    pass

            if "boll" in indicators:
                try:
                    boll_df = compute_bollinger(close)
                    if boll_df is not None:
                        ind["boll"] = {
                            "upper": [round(v, 2) if pd.notna(v) else None
                                     for v in boll_df["upper"].tolist()],
                            "middle": [round(v, 2) if pd.notna(v) else None
                                      for v in boll_df["middle"].tolist()],
                            "lower": [round(v, 2) if pd.notna(v) else None
                                     for v in boll_df["lower"].tolist()],
                        }
                except Exception:
                    pass

            result["indicators"] = ind
            return result

        return await asyncio.to_thread(_fetch_and_compute)

    async def get_financial_data(self, code: str) -> dict:
        """获取财务数据"""
        fetcher = self.fetcher

        def _fetch():
            data = fetcher.get_financial_data(code)
            if data:
                return {
                    "code": code,
                    "pe": data.pe,
                    "pb": data.pb,
                    "roe": data.roe,
                    "revenue_growth": data.revenue_growth,
                    "profit_growth": data.profit_growth,
                    "gross_margin": data.gross_margin,
                    "net_margin": data.net_margin,
                    "debt_ratio": data.debt_ratio,
                    "dividend_yield": data.dividend_yield,
                    "total_market_cap": data.total_market_cap,
                }
            return {"code": code, "error": "无财务数据"}

        return await asyncio.to_thread(_fetch)
