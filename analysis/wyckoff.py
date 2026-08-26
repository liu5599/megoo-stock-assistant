"""
威科夫吸筹引擎 —— 主力行为识别（学习自「老猫与指标」威科夫操盘法）
================================================================
核心逻辑：识别主力吸筹(Accumulation)阶段的四个关键事件：

  1. 吸筹区间识别：横盘 + 缩量 + 振幅收窄（主力悄悄建仓的"脚印"）
  2. Spring（弹簧测试）：跌破区间下沿后快速收回 = 最后一次洗盘 = 最佳抄底点
  3. SOS（强势信号）：放量突破区间上沿 = 主升启动确认
  4. 量价行为评分：放量滞涨(派发)/缩量回调(吸筹)/放量上攻(健康)

输出：
  - phase: 吸筹初期/吸筹中/拉升前夜/派发/下跌/未知
  - spring_signal: True/False（抄底信号！）
  - sos_signal: True/False（突破信号）
  - accumulation_score: 0-100（吸筹置信度）
  - 关键价位：区间上沿/下沿/当前价距下沿%
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from utils.logger import logger


class WyckoffAnalyzer:
    """威科夫吸筹分析器"""

    def __init__(self, lookback: int = 120, zone_percentile: float = 0.65):
        """
        Args:
            lookback: 分析窗口（交易日）
            zone_percentile: 区间定义分位数（0.65=中65%区域）
        """
        self.lookback = lookback
        self.zone_percentile = zone_percentile

    def analyze(self, df: pd.DataFrame) -> Dict:
        """完整威科夫分析"""
        df = getattr(df, "df", df)
        if df is None or df.empty or len(df) < 60:
            return {"phase": "未知", "spring_signal": False, "sos_signal": False,
                    "accumulation_score": 0, "reason": "数据不足"}

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        price = float(close.iloc[-1])

        # 近期窗口
        win = df.tail(self.lookback).copy()
        w_close = win["close"]
        w_high = win["high"]
        w_low = win["low"]
        w_vol = win["volume"]

        # ---- 1. 吸筹区间识别 ----
        zone_high = float(w_close.quantile(1 - (1 - self.zone_percentile) / 2))
        zone_low = float(w_close.quantile((1 - self.zone_percentile) / 2))
        range_pct = (zone_high - zone_low) / zone_low * 100

        # 横盘判定：区间内波动收窄（近30日振幅 vs 前90日）
        recent_range = (w_high.tail(30).max() - w_low.tail(30).min()) / w_low.tail(30).min() * 100
        prior_range = (w_high.head(30).max() - w_low.head(30).min()) / w_low.head(30).min() * 100

        # 缩量判定：近期均量 vs 前期均量
        recent_vol = float(w_vol.tail(30).mean())
        prior_vol = float(w_vol.head(30).mean()) if len(w_vol) >= 60 else recent_vol
        vol_shrink = recent_vol / prior_vol if prior_vol > 0 else 1.0

        # 吸筹评分
        accumulation_score = 50.0
        if range_pct < 25:
            accumulation_score += 10      # 区间窄
        if recent_range < prior_range * 0.8:
            accumulation_score += 10      # 振幅收窄
        if vol_shrink < 0.8:
            accumulation_score += 15      # 显著缩量（吸筹特征）
        elif vol_shrink < 1.0:
            accumulation_score += 5
        # 价格在区间下半部（低位横盘）
        pos_in_zone = (price - zone_low) / (zone_high - zone_low) if zone_high > zone_low else 0.5
        if pos_in_zone < 0.4:
            accumulation_score += 10

        # ---- 2. Spring 检测（最近5日跌破下沿后收回） ----
        spring_signal = False
        spring_note = ""
        for i in range(max(5, len(close) - 5), len(close)):
            if float(low.iloc[i]) < zone_low:
                # 跌破后 N 日内收回
                if price > zone_low:
                    spring_signal = True
                    spring_note = f"跌破区间下沿({zone_low:.2f})后快速收回，弹簧测试"
                    accumulation_score += 15
                break

        # ---- 3. SOS 检测（放量突破区间上沿） ----
        sos_signal = False
        if price > zone_high:
            vol_ratio = float(volume.tail(3).mean()) / prior_vol if prior_vol > 0 else 1.0
            if vol_ratio > 1.2:
                sos_signal = True
                accumulation_score += 10

        # ---- 4. 量价行为评分 ----
        vp_score = self._volume_price_score(win)
        accumulation_score = min(100, max(0, accumulation_score + (vp_score - 50) * 0.3))

        # ---- 阶段判定 ----
        phase = self._phase(accumulation_score, price, zone_low, zone_high, sos_signal)

        return {
            "phase": phase,
            "spring_signal": spring_signal,
            "sos_signal": sos_signal,
            "accumulation_score": round(accumulation_score, 1),
            "zone_high": round(zone_high, 2),
            "zone_low": round(zone_low, 2),
            "position_in_zone": round(pos_in_zone * 100, 1),
            "range_pct": round(range_pct, 1),
            "vol_shrink": round(vol_shrink, 2),
            "spring_note": spring_note,
            "reason": self._reason(spring_signal, sos_signal, phase, pos_in_zone),
        }

    @staticmethod
    def _volume_price_score(win: pd.DataFrame) -> float:
        """量价行为评分：放量上攻/缩量回调=健康，放量滞涨/缩量下跌=危险"""
        try:
            close = win["close"]
            vol = win["volume"]
            ret5 = float(close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0
            vol5 = float(vol.tail(5).mean())
            vol_prev = float(vol.tail(15).head(10).mean()) if len(vol) >= 15 else vol5
            ratio = vol5 / vol_prev if vol_prev > 0 else 1.0

            if ret5 > 3 and ratio > 1.3:
                return 80   # 放量上攻
            if -2 < ret5 < 2 and ratio < 0.8:
                return 70   # 缩量横盘（吸筹）
            if ret5 > 5 and ratio < 0.8:
                return 45   # 缩量上涨（乏力）
            if ret5 < -3 and ratio > 1.3:
                return 20   # 放量下跌（危险）
            if ret5 < -2 and ratio < 0.8:
                return 35   # 缩量下跌（抛压衰竭）
            return 55
        except Exception:
            return 50

    @staticmethod
    def _phase(score: float, price: float, zone_low: float, zone_high: float, sos: bool) -> str:
        if sos:
            return "拉升初期"
        if score >= 75 and price < zone_high:
            return "吸筹完成/拉升前夜"
        if score >= 60:
            return "吸筹中"
        if score >= 45:
            return "吸筹初期"
        if price > zone_high:
            return "拉升/派发观察"
        return "下跌/未知"

    @staticmethod
    def _reason(spring: bool, sos: bool, phase: str, pos: float) -> str:
        if spring:
            return "⚠️ Spring弹簧测试出现：主力最后洗盘，是教科书级抄底点（跌破区间下沿后快速收回）"
        if sos:
            return "🚀 SOS强势信号：放量突破吸筹区间，主升浪启动确认"
        if phase == "吸筹完成/拉升前夜":
            return "主力吸筹接近完成，关注放量突破（SOS）信号"
        if phase in ("吸筹中", "吸筹初期"):
            return f"主力正在低位吸筹（价格处于区间{pos:.0f}%位置），可分批潜伏"
        return "无明显吸筹特征，观望"


def analyze_wyckoff(df: pd.DataFrame) -> Dict:
    """便捷函数"""
    return WyckoffAnalyzer().analyze(df)
