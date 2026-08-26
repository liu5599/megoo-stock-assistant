"""
三维决策（定买卖）— 对标「指南针长线决策/波段决策/短线决策」
=========================================================
三套决策信号，对应三种持仓周期：
  1. 长线决策（趋势）：周线 MA20/MA60 多头排列 + 月线级别方向 —— 加号做多 / 减号做空
  2. 波段决策（波段）：日线 MACD 金叉死叉 + BOLL 中轨 + KDJ 共振
  3. 短线决策（短线）：5日动量 + 量比 + 短期均线金叉 + RSI 超卖修复

输出：每个维度给出 多/空/观望 信号 + 强度 + 理由，综合得出建议动作。
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from analysis.indicators import (
    compute_ema, compute_macd, detect_macd_cross,
    compute_rsi, compute_kdj, compute_bollinger,
    compute_volume_ratio,
)
from utils.logger import logger


def _as_df(df):
    """兼容 DataFrame / KLineData 包装对象"""
    if hasattr(df, "df") and isinstance(df.df, pd.DataFrame):
        return df.df
    return df


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """日线 → 周线（用于长线趋势判断）"""
    if df.empty:
        return df
    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    weekly = df.resample("W-FRI").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum",
    }).dropna()
    return weekly.reset_index()


# ═══════════════════════════════════════════════════════════════
# 三维决策器
# ═══════════════════════════════════════════════════════════════

class DecisionSignals:
    """三维决策 —— 长线/波段/短线信号合成"""

    def __init__(self):
        pass

    # ---------------- 1. 长线决策（周线趋势） ----------------

    def long_term(self, df: pd.DataFrame) -> Dict:
        """长线趋势：周线 MA20/MA60 排列 + 价格位置"""
        df = _as_df(df)
        if df is None or df.empty or len(df) < 70:
            return {"signal": "观望", "score": 50, "reason": "数据不足，无法判断长线趋势", "icon": "观望"}

        weekly = _resample_weekly(df)
        if len(weekly) < 70:
            return {"signal": "观望", "score": 50, "reason": "周线数据不足", "icon": "观望"}

        close = weekly["close"]
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        price = float(close.iloc[-1])
        ma20_v = float(ma20.iloc[-1])
        ma60_v = float(ma60.iloc[-1])
        if pd.isna(ma20_v) or pd.isna(ma60_v):
            return {"signal": "观望", "score": 50, "reason": "均线数据不足", "icon": "观望"}

        score = 50
        reasons = []
        # 多头排列：MA20 > MA60 且 价格 > MA20
        if ma20_v > ma60_v and price > ma20_v:
            score += 25
            reasons.append("周线多头排列(MA20>MA60)，趋势向上")
        elif ma20_v < ma60_v and price < ma20_v:
            score -= 25
            reasons.append("周线空头排列(MA20<MA60)，趋势向下")
        elif price > ma20_v:
            score += 10
            reasons.append("价格站上20周均线，偏多")
        else:
            score -= 10
            reasons.append("价格跌破20周均线，偏空")

        # 60周均线作为牛熊分界
        if price > ma60_v:
            score += 10
            reasons.append("价格站上60周牛熊线")
        else:
            score -= 10
            reasons.append("价格位于60周牛熊线下方")

        score = max(0, min(100, score))
        signal = "多" if score >= 65 else ("空" if score <= 35 else "观望")
        return {
            "signal": signal,
            "score": score,
            "price": round(price, 2),
            "ma20": round(ma20_v, 2),
            "ma60": round(ma60_v, 2),
            "reason": "；".join(reasons),
            "icon": "加号做多" if signal == "多" else ("减号做空" if signal == "空" else "观望"),
        }

    # ---------------- 2. 波段决策（日线共振） ----------------

    def swing(self, df: pd.DataFrame) -> Dict:
        """波段：MACD 金叉/死叉 + BOLL 位置 + KDJ 共振"""
        df = _as_df(df)
        if df is None or df.empty or len(df) < 40:
            return {"signal": "观望", "score": 50, "reason": "数据不足，无法判断波段"}

        close = df["close"]
        high, low = df["high"], df["low"]
        price = float(close.iloc[-1])

        score = 50
        reasons = []

        # MACD（返回 DataFrame: dif/dea/macd）
        macd_df = compute_macd(close)
        dif = macd_df["dif"]
        dea = macd_df["dea"]
        if len(dif) > 2 and not pd.isna(dif.iloc[-1]) and not pd.isna(dea.iloc[-1]):
            cross = detect_macd_cross(dif, dea)
            if len(cross) >= 2:
                last = int(cross.iloc[-1])
                if last == 1:
                    score += 20
                    reasons.append("MACD金叉")
                elif last == -1:
                    score -= 20
                    reasons.append("MACD死叉")
            if dif.iloc[-1] > 0:
                score += 8
                reasons.append("DIF在零轴上方")
            else:
                score -= 8
                reasons.append("DIF在零轴下方")

        # BOLL
        try:
            upper, mid, lower = compute_bollinger(close)
            if not pd.isna(upper.iloc[-1]):
                if price > upper.iloc[-1]:
                    score -= 8
                    reasons.append("突破布林上轨(超买)")
                elif price < lower.iloc[-1]:
                    score += 12
                    reasons.append("触及布林下轨(超卖)")
                elif price > mid.iloc[-1]:
                    score += 5
                    reasons.append("位于布林中轨上方")
                else:
                    score -= 5
                    reasons.append("位于布林中轨下方")
        except Exception:
            pass

        # KDJ
        try:
            k, d, j = compute_kdj(high, low, close)
            if not pd.isna(k.iloc[-1]) and not pd.isna(d.iloc[-1]):
                if k.iloc[-1] > d.iloc[-1]:
                    score += 7
                    reasons.append("KDJ金叉")
                else:
                    score -= 7
                    reasons.append("KDJ死叉")
                if j.iloc[-1] < 20:
                    score += 8
                    reasons.append("KDJ超卖")
                elif j.iloc[-1] > 80:
                    score -= 8
                    reasons.append("KDJ超买")
        except Exception:
            pass

        score = max(0, min(100, score))
        signal = "多" if score >= 65 else ("空" if score <= 35 else "观望")
        return {
            "signal": signal,
            "score": score,
            "reason": "；".join(reasons) or "无显著波段信号",
        }

    # ---------------- 3. 短线决策（5日博弈） ----------------

    def short_term(self, df: pd.DataFrame) -> Dict:
        """短线：5日动量 + 量比 + 短期均线金叉 + RSI"""
        df = _as_df(df)
        if df is None or df.empty or len(df) < 20:
            return {"signal": "观望", "score": 50, "reason": "数据不足，无法判断短线"}

        close = df["close"]
        price = float(close.iloc[-1])
        score = 50
        reasons = []

        # 5日动量
        if len(close) >= 6:
            mom = (price / float(close.iloc[-6]) - 1) * 100
            if mom > 5:
                score += 15
                reasons.append(f"5日动量强(+{mom:.1f}%)")
            elif mom > 0:
                score += 5
                reasons.append(f"5日动量偏多(+{mom:.1f}%)")
            elif mom < -5:
                score -= 15
                reasons.append(f"5日动量弱({mom:.1f}%)")
            else:
                score -= 5
                reasons.append(f"5日动量偏空({mom:.1f}%)")

        # 量比
        try:
            vr = compute_volume_ratio(df["volume"])
            if not pd.isna(vr.iloc[-1]):
                if vr.iloc[-1] > 2:
                    score += 10
                    reasons.append(f"量比{vr.iloc[-1]:.1f}放量")
                elif vr.iloc[-1] > 1.2:
                    score += 3
                    reasons.append(f"量比{vr.iloc[-1]:.1f}温和放量")
                elif vr.iloc[-1] < 0.6:
                    score -= 8
                    reasons.append(f"量比{vr.iloc[-1]:.1f}缩量")
        except Exception:
            pass

        # 5/10日短期均线
        if len(close) >= 10:
            ma5 = float(close.rolling(5).mean().iloc[-1])
            ma10 = float(close.rolling(10).mean().iloc[-1])
            if ma5 > ma10 and price > ma5:
                score += 10
                reasons.append("5日线上穿10日线")
            elif ma5 < ma10 and price < ma5:
                score -= 10
                reasons.append("5日线下穿10日线")

        # RSI
        try:
            rsi = compute_rsi(close)
            if not pd.isna(rsi.iloc[-1]):
                if rsi.iloc[-1] > 75:
                    score -= 10
                    reasons.append(f"RSI超买({rsi.iloc[-1]:.0f})")
                elif rsi.iloc[-1] < 30:
                    score += 12
                    reasons.append(f"RSI超卖({rsi.iloc[-1]:.0f})")
                elif rsi.iloc[-1] > 55:
                    score += 4
                    reasons.append(f"RSI偏强({rsi.iloc[-1]:.0f})")
        except Exception:
            pass

        score = max(0, min(100, score))
        signal = "多" if score >= 65 else ("空" if score <= 35 else "观望")
        return {
            "signal": signal,
            "score": score,
            "reason": "；".join(reasons) or "无显著短线信号",
        }

    # ---------------- 综合 ----------------

    def comprehensive(self, df: pd.DataFrame) -> Dict:
        """三维综合：长线 40% + 波段 35% + 短线 25%"""
        lt = self.long_term(df)
        sw = self.swing(df)
        st = self.short_term(df)

        total = lt["score"] * 0.4 + sw["score"] * 0.35 + st["score"] * 0.25
        total = max(0, min(100, total))

        if total >= 65:
            action = "买入/加仓"
        elif total <= 35:
            action = "卖出/减仓"
        else:
            action = "持有/观望"

        return {
            "long_term": lt,
            "swing": sw,
            "short_term": st,
            "composite_score": round(total, 1),
            "action": action,
        }

    def analyze(self, df: pd.DataFrame) -> Dict:
        return self.comprehensive(df)


def get_signals(df: pd.DataFrame) -> Dict:
    """便捷函数"""
    return DecisionSignals().comprehensive(df)
