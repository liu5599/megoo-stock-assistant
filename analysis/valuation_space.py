"""
估值空间（定风险区）— 对标「指南针估值空间：安全边界/价值中枢/风险警戒」
======================================================================
以个股 PE-TTM/PB 的历史分位数定位当前估值处于哪个区域：
  - 安全边界区：估值分位 < 20%  → 低估，临近价值回归
  - 价值中枢区：估值分位 20-70% → 合理，正常波动
  - 风险警戒区：估值分位 > 70%  → 高估，临近回调风险

数据源：akshare 乐咕个股指标（历史 PE/PB）
"""
import time
from typing import Dict, List, Optional

import pandas as pd

from utils.logger import logger


def _safe_call(func, *args, retries: int = 2, **kwargs):
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < retries:
                logger.warning(f"akshare调用失败({attempt+1}/{retries+1}): {e}，重试...")
                time.sleep(1.0)
            else:
                logger.error(f"akshare调用最终失败: {e}")
                return None


def fetch_pe_pb_history(symbol: str) -> Optional[pd.DataFrame]:
    """个股历史 PE(TTM)/PB
    优先：Tushare daily_basic（付费兜底，数据全）
    兜底：东财 stock_value_em（免费，2018年至今）
    """
    # 1. Tushare 优先
    try:
        from data.tushare_fetcher import tushare_enabled, fetch_daily_basic, to_ts_code
        if tushare_enabled():
            df = fetch_daily_basic(ts_code=to_ts_code(symbol))
            if df is not None and not df.empty:
                df = df.rename(columns={"trade_date": "trade_date", "pe_ttm": "pe_ttm", "pb": "pb"})
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df.sort_values("trade_date").reset_index(drop=True)
                logger.info(f"估值历史(来自Tushare): {symbol} {len(df)}行")
                return df
    except Exception as e:
        logger.warning(f"Tushare估值历史失败 {symbol}: {e}")

    # 2. 东财兜底
    ak = __import__("akshare", fromlist=["stock_value_em"])
    df = _safe_call(ak.stock_value_em, symbol=symbol)
    if df is None or df.empty:
        return None
    rename = {"数据日期": "trade_date", "PE(TTM)": "pe_ttm", "市净率": "pb"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


# ═══════════════════════════════════════════════════════════════
# 估值空间
# ═══════════════════════════════════════════════════════════════

class ValuationSpace:
    """估值空间 —— 三区分位定位"""

    ZONE_SAFE = "安全边界区"
    ZONE_CENTER = "价值中枢区"
    ZONE_WARN = "风险警戒区"

    def __init__(self, lookback_days: int = 365 * 10):
        self.lookback_days = lookback_days  # 默认近10年分位

    def classify(self, pe_pct: float, pb_pct: float) -> str:
        """按 PE/PB 分位定位区域"""
        if pe_pct < 20 and pb_pct < 20:
            return self.ZONE_SAFE
        if pe_pct > 70 or pb_pct > 70:
            return self.ZONE_WARN
        return self.ZONE_CENTER

    def analyze(self, symbol: str) -> Dict:
        """个股估值空间分析"""
        df = fetch_pe_pb_history(symbol)
        if df is None or df.empty or len(df) < 60:
            return {
                "symbol": symbol,
                "zone": self.ZONE_CENTER,
                "zone_cn": self.ZONE_CENTER,
                "pe": None, "pb": None,
                "pe_pct": None, "pb_pct": None,
                "reason": "估值历史数据不足，无法定位",
                "available": False,
            }

        recent = df.tail(self.lookback_days).copy()
        cur = recent.iloc[-1]
        pe = float(cur.get("pe_ttm") or cur.get("pe") or 0)
        pb = float(cur.get("pb") or 0)

        pe_pct = None
        pb_pct = None
        if pe > 0:
            pe_pct = round(float((recent["pe_ttm"] < pe).mean()) * 100, 1) if "pe_ttm" in recent.columns else None
        if pb > 0:
            pb_pct = round(float((recent["pb"] < pb).mean()) * 100, 1) if "pb" in recent.columns else None

        if pe_pct is None or pb_pct is None:
            return {
                "symbol": symbol, "zone": self.ZONE_CENTER, "zone_cn": self.ZONE_CENTER,
                "pe": pe, "pb": pb, "pe_pct": pe_pct, "pb_pct": pb_pct,
                "reason": "估值数据不完整", "available": False,
            }

        zone = self.classify(pe_pct, pb_pct)
        if zone == self.ZONE_SAFE:
            reason = f"PE分位{pe_pct:.0f}%/PB分位{pb_pct:.0f}%，处于历史低位，安全边界，具备估值修复空间"
        elif zone == self.ZONE_WARN:
            reason = f"PE分位{pe_pct:.0f}%/PB分位{pb_pct:.0f}%，处于历史高位，风险警戒，谨防估值回调"
        else:
            reason = f"PE分位{pe_pct:.0f}%/PB分位{pb_pct:.0f}%，处于历史中枢，估值合理"

        return {
            "symbol": symbol,
            "zone": zone,
            "zone_cn": zone,
            "pe": round(pe, 2),
            "pb": round(pb, 2),
            "pe_pct": pe_pct,
            "pb_pct": pb_pct,
            "reason": reason,
            "available": True,
            "trade_date": cur.get("trade_date", "").strftime("%Y-%m-%d") if hasattr(cur.get("trade_date", ""), "strftime") else str(cur.get("trade_date", "")),
        }


def get_valuation(symbol: str) -> Dict:
    """便捷函数"""
    return ValuationSpace().analyze(symbol)
