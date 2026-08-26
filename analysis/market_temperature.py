"""
市场温度计（判大势）— 对标「指南针估值空间 + 容维情绪」
====================================================
融合三路信号得出大盘温度：
  1. 市场情绪（乐咕活跃度：涨跌家数比、涨停/跌停数）—— 容维情绪维度
  2. 量能资金（成交额、量能水平）                    —— 指南针资金维度
  3. 估值分位（上证 PE/PB 历史分位）                —— 指南针「安全边界/价值中枢/风险警戒」

温度语义（0-100）：
  温度高 → 风险警戒区 → 减仓/防守
  温度中 → 价值中枢区 → 持有/均衡
  温度低 → 安全边界区 → 临近触底，可布局

核心结论：温度 = 情绪*0.4 + 量能*0.2 + 估值*0.4（估值分位越低 → 温度越低 → 越安全）
"""
import datetime
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from utils.logger import logger
from analysis._cache import ttl_cache


# ═══════════════════════════════════════════════════════════════
# 数据获取（akshare + 容错降级）
# ═══════════════════════════════════════════════════════════════

def _safe_call(func, *args, retries: int = 2, **kwargs):
    """akshare 调用容错：重试 + 返回 None"""
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


@ttl_cache(300)
def fetch_market_activity() -> Optional[Dict]:
    """乐咕市场活跃度：上涨/下跌/平盘/涨停/跌停家数（缓存5分钟）"""
    df = _safe_call(__import__("akshare", fromlist=["stock_market_activity_legu"]).stock_market_activity_legu)
    if df is None or df.empty:
        return None
    # 列名形如: item, value
    data = dict(zip(df["item"].astype(str), df["value"]))
    return data


@ttl_cache(3600)
def fetch_index_valuation(symbol: str = "上证50") -> Optional[pd.DataFrame]:
    """大盘历史 PE-TTM（乐咕指数估值接口，缓存1小时）"""
    ak = __import__("akshare", fromlist=["stock_index_pe_lg"])
    df = _safe_call(ak.stock_index_pe_lg, symbol=symbol)
    if df is None or df.empty:
        return None
    # 列名: 日期/指数/等权静态市盈率/静态市盈率/静态市盈率中位数/等权滚动市盈率/滚动市盈率/滚动市盈率中位数
    rename = {"日期": "trade_date", "滚动市盈率": "pe_ttm"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


# ═══════════════════════════════════════════════════════════════
# 市场温度计
# ═══════════════════════════════════════════════════════════════

class MarketTemperature:
    """市场温度计 —— 判断大盘当前处于 安全边界/价值中枢/风险警戒 哪个区域"""

    # 区域映射
    ZONE_SAFE = "安全边界区"
    ZONE_CENTER = "价值中枢区"
    ZONE_WARN = "风险警戒区"
    ZONE_EXTREME = "极端区"

    def __init__(self, index_symbol: str = "上证50"):
        self.index_symbol = index_symbol

    # ---------------- 各维度评分 ----------------

    def _score_emotion(self, activity: Dict) -> float:
        """情绪分：涨跌家数比 + 涨停数"""
        try:
            up = float(activity.get("上涨", 0))
            down = float(activity.get("下跌", 0))
            limit_up = float(activity.get("涨停", 0))
            limit_down = float(activity.get("跌停", 0))
            total = up + down
            if total <= 0:
                return 50.0
            up_ratio = up / total
            # 涨跌比 → 0-100
            score = up_ratio * 100
            # 涨停家数修正：>80家=情绪亢奋，<10家=情绪冰点
            if limit_up >= 80:
                score = min(100, score + 15)
            elif limit_up <= 10:
                score = max(0, score - 15)
            if limit_down >= 30:
                score = max(0, score - 20)
            return round(score, 1)
        except Exception:
            return 50.0

    def _score_volume(self, activity: Dict) -> float:
        """量能分：成交额水平（近一年经验阈值）"""
        try:
            amount = float(activity.get("成交额", 0))  # 单位通常是亿元
            # A股两市场日成交：<6000亿=地量(低温)，>15000亿=天量(高温)
            if amount <= 0:
                return 50.0
            if amount >= 15000:
                return 90.0
            elif amount >= 12000:
                return 75.0
            elif amount >= 9000:
                return 60.0
            elif amount >= 6000:
                return 40.0
            else:
                return 20.0
        except Exception:
            return 50.0

    def _score_valuation(self, val_df: pd.DataFrame, pe_col: str = "pe_ttm") -> float:
        """估值分：当前 PE 在近10年分位 → 分位越高温度越高（越危险）"""
        try:
            if val_df is None or val_df.empty or len(val_df) < 60:
                return 50.0
            # 取近10年（约2500交易日）
            recent = val_df.tail(2500).copy()
            cur_pe = float(recent.iloc[-1][pe_col])
            if pd.isna(cur_pe) or cur_pe <= 0:
                return 50.0
            pct = (recent[pe_col] < cur_pe).mean() * 100
            return round(pct, 1)
        except Exception:
            return 50.0

    # ---------------- 综合 ----------------

    def compute_temperature(self) -> Dict:
        """综合三路信号输出市场温度与区域判断"""
        activity = fetch_market_activity()
        val_df = fetch_index_valuation(self.index_symbol)

        emotion = self._score_emotion(activity or {})
        volume = self._score_volume(activity or {})
        valuation = self._score_valuation(val_df)

        # 温度 = 情绪*0.4 + 量能*0.2 + 估值*0.4
        temperature = round(emotion * 0.4 + volume * 0.2 + valuation * 0.4, 1)

        if temperature >= 85:
            zone, advice = self.ZONE_EXTREME, "市场极度亢奋，坚决减仓防守，落袋为安"
        elif temperature >= 70:
            zone, advice = self.ZONE_WARN, "风险警戒区：高位过热，控制仓位，只做强势股快进快出"
        elif temperature >= 45:
            zone, advice = self.ZONE_CENTER, "价值中枢区：多空均衡，精选个股，维持中性仓位"
        elif temperature >= 25:
            zone, advice = self.ZONE_SAFE, "安全边界区：临近触底反弹，可分批布局优质标的"
        else:
            zone, advice = self.ZONE_EXTREME, "市场冰点：极度低估，长线资金可大胆布局，耐心持有"

        return {
            "temperature": temperature,
            "zone": zone,
            "advice": advice,
            "scores": {
                "emotion": emotion,      # 情绪分
                "volume": volume,        # 量能分
                "valuation": valuation,  # 估值分位
            },
            "details": {
                "activity": activity or {},
                "valuation_pct": valuation,
            },
            "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def to_dict(self) -> Dict:
        return clean_jsonable(self.compute_temperature())


# ═══════════════════════════════════════════════════════════════
# 数据清洗（NaN/Inf 不是合法 JSON，API 返回前必须清洗）
# ═══════════════════════════════════════════════════════════════

def clean_jsonable(obj):
    """递归清洗 NaN/Inf/np/date 类型 → JSON 兼容"""
    if isinstance(obj, dict):
        return {k: clean_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_jsonable(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, (np.integer, int)) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


# 便捷函数
def get_market_temperature() -> Dict:
    """获取当前市场温度（供 Web/日报调用）"""
    return clean_jsonable(MarketTemperature().compute_temperature())
