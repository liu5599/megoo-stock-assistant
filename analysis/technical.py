"""
技术分析器
=========
基于K线数据计算各类技术指标，生成技术面分析摘要和评分。
分析维度：均线趋势、MACD信号、RSI状态、KDJ信号、布林带位置、量价关系。
"""

from typing import List, Optional
import pandas as pd

from data.models import KLineData, TechnicalSummary
from analysis.indicators import (
    compute_multi_ma, compute_macd, compute_rsi, compute_kdj,
    compute_bollinger, compute_volume_ma, compute_volume_ratio,
    compute_price_momentum, compute_volatility, compute_support_resistance,
    compute_atr, compute_adx, detect_macd_cross,
)
from config.settings import AppConfig, default_config
from utils.helpers import clamp
from utils.logger import logger


class TechnicalAnalyzer:
    """
    技术分析器
    ==========
    输入K线数据，输出技术指标DataFrame及各维度信号。

    评分权重分配：
    - 均线趋势: 25%
    - MACD信号: 20%
    - RSI状态: 15%
    - KDJ信号: 15%
    - 布林带: 15%
    - 量价关系: 10%
    """

    def __init__(self, kline: KLineData, config: AppConfig = None):
        """
        Args:
            kline: K线数据
            config: 应用配置
        """
        self.data = kline
        self.config = config or default_config
        self.df = kline.df.copy() if not kline.df.empty else pd.DataFrame()

        # 懒加载缓存
        self._indicators: Optional[pd.DataFrame] = None
        self._ma_df: Optional[pd.DataFrame] = None
        self._macd_df: Optional[pd.DataFrame] = None
        self._rsi_series: Optional[pd.Series] = None
        self._kdj_df: Optional[pd.DataFrame] = None
        self._boll_df: Optional[pd.DataFrame] = None
        self._adx_df: Optional[pd.DataFrame] = None

    # ======================== 指标计算（懒加载） ========================

    def compute_all_indicators(self) -> pd.DataFrame:
        """一次性计算并缓存所有指标"""
        if self._indicators is not None:
            return self._indicators

        if self.df.empty:
            logger.warning("K线数据为空，无法计算指标")
            self._indicators = pd.DataFrame()
            return self._indicators

        close = self.df["close"]
        high = self.df["high"]
        low = self.df["low"]
        volume = self.df["volume"]

        indicators = pd.DataFrame(index=self.df.index)

        # 均线
        ma_df = compute_multi_ma(close, self.config.MA_PERIODS)
        for col in ma_df.columns:
            indicators[col] = ma_df[col]

        # MACD
        macd_df = compute_macd(close, self.config.MACD_FAST,
                               self.config.MACD_SLOW, self.config.MACD_SIGNAL)
        for col in macd_df.columns:
            indicators[col] = macd_df[col]

        # RSI
        indicators["rsi"] = compute_rsi(close, self.config.RSI_PERIOD)

        # KDJ
        kdj_df = compute_kdj(high, low, close, self.config.KDJ_N,
                              self.config.KDJ_K, self.config.KDJ_D)
        for col in kdj_df.columns:
            indicators[col] = kdj_df[col]

        # 布林带
        boll_df = compute_bollinger(close, self.config.BOLL_PERIOD,
                                     self.config.BOLL_STD)
        for col in boll_df.columns:
            indicators[f"boll_{col}"] = boll_df[col]

        # 成交量分析
        indicators["volume_ma"] = compute_volume_ma(volume, self.config.VOLUME_MA_PERIOD)
        indicators["volume_ratio"] = compute_volume_ratio(volume)

        # 价格动量
        indicators["momentum_20"] = compute_price_momentum(close, 20)
        indicators["momentum_60"] = compute_price_momentum(close, 60)

        # 波动率
        indicators["volatility_20"] = compute_volatility(close, 20)

        # ATR
        indicators["atr"] = compute_atr(high, low, close)

        # ADX
        adx_df = compute_adx(high, low, close)
        for col in adx_df.columns:
            indicators[col] = adx_df[col]

        self._indicators = indicators
        self._ma_df = ma_df
        self._macd_df = macd_df
        self._rsi_series = indicators["rsi"]
        self._kdj_df = kdj_df
        self._boll_df = boll_df
        self._adx_df = adx_df

        return indicators

    @property
    def indicators(self) -> pd.DataFrame:
        """获取所有指标（懒加载）"""
        if self._indicators is None:
            self.compute_all_indicators()
        return self._indicators

    # ======================== 各维度信号分析 ========================

    def get_trend_signal(self) -> dict:
        """
        均线趋势信号分析

        判断标准：
        - 多头排列 (MA5>MA10>MA20>MA60): 看多
        - 空头排列 (MA5<MA10<MA20<MA60): 看空
        - 其他: 震荡

        Returns:
            {'direction': 'bull'|'bear'|'sideways', 'strength': 0-100,
             'ma_bull_count': N, 'ma_bear_count': N}
        """
        if self.df.empty or len(self.df) < 60:
            return {"direction": "sideways", "strength": 50}

        close = self.df["close"]
        latest_close = close.iloc[-1]

        # 从已缓存的指标中读取均线值，避免重复计算
        indicators_df = self.indicators  # 触发懒加载
        ma_values = {}
        for p in [5, 10, 20, 60, 120]:
            col = f"ma{p}"
            if col in indicators_df.columns:
                val = indicators_df[col].iloc[-1]
                ma_values[p] = val if not pd.isna(val) else None
            else:
                ma_values[p] = None

        # 价格相对于各均线的位置
        above_count = sum(1 for v in ma_values.values()
                          if v is not None and latest_close > v)
        below_count = sum(1 for v in ma_values.values()
                          if v is not None and latest_close < v)

        # 均线排列判断
        valid_mas = [ma_values[p] for p in [5, 10, 20, 60] if ma_values[p] is not None]
        is_bull_arrange = len(valid_mas) >= 3 and all(
            valid_mas[i] > valid_mas[i + 1] for i in range(len(valid_mas) - 1)
        )
        is_bear_arrange = len(valid_mas) >= 3 and all(
            valid_mas[i] < valid_mas[i + 1] for i in range(len(valid_mas) - 1)
        )

        if is_bull_arrange:
            direction = "bull"
            strength = 70 + (above_count / max(below_count + above_count, 1)) * 30
        elif is_bear_arrange:
            direction = "bear"
            strength = 70 + (below_count / max(below_count + above_count, 1)) * 30
        else:
            direction = "sideways"
            strength = 40 + (above_count / max(below_count + above_count, 1)) * 20

        return {
            "direction": direction,
            "strength": round(clamp(strength, 0, 100), 1),
            "ma_bull_count": above_count,
            "ma_bear_count": below_count,
            "ma_arrangement": "bull" if is_bull_arrange else ("bear" if is_bear_arrange else "mixed"),
        }

    def get_macd_signal(self) -> dict:
        """
        MACD信号分析

        Returns:
            {'signal': 'golden_cross'|'death_cross'|'bullish'|'bearish'|'neutral',
             'dif': float, 'dea': float, 'macd_bar': float}
        """
        if self.df.empty:
            return {"signal": "neutral", "dif": 0, "dea": 0, "macd_bar": 0}

        macd_df = self._macd_df if self._macd_df is not None else compute_macd(
            self.df["close"], self.config.MACD_FAST,
            self.config.MACD_SLOW, self.config.MACD_SIGNAL
        )

        latest = macd_df.iloc[-1]
        dif = float(latest["dif"])
        dea = float(latest["dea"])
        macd_bar = float(latest["macd"])

        # 检查最近的金叉/死叉
        crosses = detect_macd_cross(macd_df["dif"], macd_df["dea"])
        recent_crosses = crosses.iloc[-5:]  # 最近5日
        has_golden = (recent_crosses == 1).any()
        has_death = (recent_crosses == -1).any()

        # 综合判断
        if has_golden and dif > 0 and macd_bar > 0:
            signal = "golden_cross"  # 零轴上方金叉
        elif has_golden:
            signal = "golden_cross"
        elif has_death and dif < 0:
            signal = "death_cross"
        elif dif > dea and macd_bar > 0:
            signal = "bullish"  # 多头持续
        elif dif < dea and macd_bar < 0:
            signal = "bearish"  # 空头持续
        else:
            signal = "neutral"

        return {
            "signal": signal,
            "dif": round(dif, 4),
            "dea": round(dea, 4),
            "macd_bar": round(macd_bar, 4),
        }

    def get_rsi_signal(self) -> dict:
        """RSI信号分析"""
        if self.df.empty:
            return {"value": 50, "signal": "neutral"}

        rsi = self._rsi_series if self._rsi_series is not None else \
            compute_rsi(self.df["close"], self.config.RSI_PERIOD)

        latest_rsi = float(rsi.iloc[-1])

        if latest_rsi > self.config.RSI_OVERBOUGHT:
            signal = "overbought"
        elif latest_rsi < self.config.RSI_OVERSOLD:
            signal = "oversold"
        else:
            signal = "neutral"

        return {
            "value": round(latest_rsi, 1),
            "signal": signal,
        }

    def get_kdj_signal(self) -> dict:
        """KDJ信号分析"""
        if self.df.empty:
            return {"k": 50, "d": 50, "j": 50, "signal": "neutral"}

        kdj_df = self._kdj_df if self._kdj_df is not None else compute_kdj(
            self.df["high"], self.df["low"], self.df["close"],
            self.config.KDJ_N, self.config.KDJ_K, self.config.KDJ_D
        )

        latest = kdj_df.iloc[-1]
        k_val = float(latest["k"])
        d_val = float(latest["d"])
        j_val = float(latest["j"])
        prev = kdj_df.iloc[-2] if len(kdj_df) > 1 else latest
        prev_k = float(prev["k"])

        # 信号判断
        if prev_k <= float(prev["d"]) and k_val > d_val:
            if k_val < 30:
                signal = "golden_cross_oversold"  # 低位金叉（强烈看多）
            else:
                signal = "golden_cross"
        elif prev_k >= float(prev["d"]) and k_val < d_val:
            if k_val > 70:
                signal = "death_cross_overbought"  # 高位死叉（强烈看空）
            else:
                signal = "death_cross"
        elif k_val > self.config.KDJ_OVERBOUGHT:
            signal = "overbought"
        elif k_val < self.config.KDJ_OVERSOLD:
            signal = "oversold"
        else:
            signal = "neutral"

        return {
            "k": round(k_val, 1),
            "d": round(d_val, 1),
            "j": round(j_val, 1),
            "signal": signal,
        }

    def get_bollinger_signal(self) -> dict:
        """布林带信号分析"""
        if self.df.empty or len(self.df) < 20:
            return {"signal": "neutral", "position": "middle", "bandwidth": 0}

        close = self.df["close"]
        boll_df = self._boll_df if self._boll_df is not None else \
            compute_bollinger(close, self.config.BOLL_PERIOD, self.config.BOLL_STD)

        latest = boll_df.iloc[-1]
        latest_close = close.iloc[-1]
        upper = float(latest["upper"])
        lower = float(latest["lower"])
        middle = float(latest["middle"])
        bandwidth = float(latest["bandwidth"])
        percent_b = float(latest["percent_b"])

        # 位置判断
        if latest_close >= upper * 0.995:
            position = "above_upper"  # 突破上轨
        elif latest_close <= lower * 1.005:
            position = "below_lower"  # 跌破下轨
        elif latest_close > middle:
            position = "upper_half"   # 中轨上方
        else:
            position = "lower_half"   # 中轨下方

        # 带宽变化（收窄=变盘信号）
        prev_bandwidth = float(boll_df["bandwidth"].iloc[-6:-1].mean()) \
            if len(boll_df) >= 6 else bandwidth
        is_squeezing = bandwidth < prev_bandwidth * 0.8  # 带宽收窄20%

        # 信号综合
        if position == "below_lower" and is_squeezing:
            signal = "oversold_squeeze"  # 超卖+收窄，可能反弹
        elif position == "above_upper":
            signal = "overbought"  # 超买
        elif position == "below_lower":
            signal = "oversold"  # 超卖
        elif position == "upper_half":
            signal = "bullish"  # 偏多
        else:
            signal = "bearish"  # 偏空

        return {
            "signal": signal,
            "position": position,
            "upper": round(upper, 2),
            "middle": round(middle, 2),
            "lower": round(lower, 2),
            "bandwidth": round(bandwidth, 2),
            "percent_b": round(percent_b, 2),
            "is_squeezing": is_squeezing,
        }

    def get_volume_signal(self) -> dict:
        """量价关系信号分析"""
        if self.df.empty or len(self.df) < 5:
            return {"signal": "neutral", "volume_ratio": 1.0}

        close = self.df["close"]
        volume = self.df["volume"]

        # 量比 — 从缓存中读取
        indicators_df = self.indicators
        vol_ratio = float(indicators_df["volume_ratio"].iloc[-1])

        # 近5日价格变化
        price_change_5d = float((close.iloc[-1] / close.iloc[-5] - 1) * 100)

        # 近5日均量
        avg_vol_5d = float(volume.iloc[-5:].mean())
        latest_vol = float(volume.iloc[-1])

        # 量价关系判断
        if price_change_5d > 2 and vol_ratio > 1.5:
            signal = "volume_up_price_up"      # 放量上涨（强势）
        elif price_change_5d > 2 and vol_ratio < 0.7:
            signal = "volume_down_price_up"    # 缩量上涨（需警惕）
        elif price_change_5d < -2 and vol_ratio > 1.5:
            signal = "volume_up_price_down"    # 放量下跌（弱势）
        elif price_change_5d < -2 and vol_ratio < 0.7:
            signal = "volume_down_price_down"  # 缩量下跌（可能止跌）
        elif vol_ratio > 1.5:
            signal = "high_volume"             # 放量震荡
        elif vol_ratio < 0.5:
            signal = "low_volume"              # 地量
        else:
            signal = "normal"

        return {
            "signal": signal,
            "volume_ratio": round(vol_ratio, 2),
            "latest_volume": latest_vol,
            "avg_volume_5d": round(avg_vol_5d, 0),
            "price_change_5d": round(price_change_5d, 2),
        }

    # ======================== 综合评分与摘要 ========================

    def get_technical_summary(self) -> TechnicalSummary:
        """
        技术面综合摘要
        ==============
        汇总各子指标信号，加权计算技术面总体评分。

        Returns:
            TechnicalSummary: 包含趋势判断、评分、关键价位等
        """
        if self.df.empty or len(self.df) < 20:
            return TechnicalSummary()

        # 强制计算所有指标
        self.compute_all_indicators()

        # 获取各维度信号
        trend = self.get_trend_signal()
        macd = self.get_macd_signal()
        rsi = self.get_rsi_signal()
        kdj = self.get_kdj_signal()
        boll = self.get_bollinger_signal()
        volume = self.get_volume_signal()

        # ===== 评分计算 =====
        scores = {}

        # 1. 均线趋势评分 (25%)
        trend_map = {"bull": 90, "bear": 15, "sideways": 50}
        base_trend_score = trend_map.get(trend["direction"], 50)
        scores["均线趋势"] = base_trend_score

        # 2. MACD评分 (20%)
        macd_signal_map = {
            "golden_cross": 85, "bullish": 70,
            "neutral": 50, "bearish": 30, "death_cross": 15,
        }
        scores["MACD"] = macd_signal_map.get(macd["signal"], 50)

        # 3. RSI评分 (15%)
        rsi_val = rsi["value"]
        if 40 <= rsi_val <= 60:
            scores["RSI"] = 80  # 中性区间最优
        elif 30 <= rsi_val < 40:
            scores["RSI"] = 60 + (rsi_val - 30) * 2  # 偏低位
        elif 60 < rsi_val <= 70:
            scores["RSI"] = 60 - (rsi_val - 60) * 2  # 偏高
        elif rsi_val < 30:
            scores["RSI"] = 40 - (30 - rsi_val) * 2  # 超卖（可能是机会）
        else:  # > 70
            scores["RSI"] = max(10, 40 - (rsi_val - 70) * 2)  # 超买

        # 4. KDJ评分 (15%)
        kdj_signal_map = {
            "golden_cross_oversold": 90,
            "golden_cross": 75,
            "neutral": 50,
            "oversold": 55,
            "overbought": 35,
            "death_cross": 25,
            "death_cross_overbought": 10,
        }
        scores["KDJ"] = kdj_signal_map.get(kdj["signal"], 50)

        # 5. 布林带评分 (15%)
        boll_signal_map = {
            "oversold_squeeze": 80,  # 下轨+收窄，反弹信号
            "oversold": 60,
            "bullish": 75,
            "bearish": 35,
            "overbought": 25,
        }
        scores["布林带"] = boll_signal_map.get(boll["signal"], 50)

        # 6. 量价关系评分 (10%)
        volume_signal_map = {
            "volume_up_price_up": 85,      # 放量上涨
            "volume_down_price_down": 55,  # 缩量下跌（可能止跌）
            "low_volume": 50,
            "normal": 50,
            "high_volume": 45,
            "volume_down_price_up": 35,    # 缩量上涨（需警惕）
            "volume_up_price_down": 15,    # 放量下跌
        }
        scores["量价关系"] = volume_signal_map.get(volume["signal"], 50)

        # 加权综合
        weights = {
            "均线趋势": 0.25, "MACD": 0.20, "RSI": 0.15,
            "KDJ": 0.15, "布林带": 0.15, "量价关系": 0.10,
        }
        total_score = sum(scores[k] * weights[k] for k in scores)

        # 支撑位和阻力位
        support_levels, resistance_levels = compute_support_resistance(
            self.df["close"], self.df["high"], self.df["low"]
        )

        # 构建摘要
        summary = TechnicalSummary(
            trend_direction=trend["direction"],
            trend_strength=round(trend["strength"], 1),
            ma_arrangement=trend["ma_arrangement"],
            macd_signal=macd["signal"],
            rsi_value=rsi["value"],
            rsi_signal=rsi["signal"],
            kdj_signal=kdj["signal"],
            bollinger_signal=boll["signal"],
            volume_signal=volume["signal"],
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            score=round(clamp(total_score, 0, 100), 1),
        )

        logger.debug(
            f"技术面评分: {summary.score} | "
            f"趋势: {summary.trend_direction} | "
            f"MACD: {summary.macd_signal} | "
            f"RSI: {summary.rsi_value}"
        )

        return summary

    def get_detailed_signals(self) -> dict:
        """获取所有信号的详细信息（用于完整报告）"""
        return {
            "trend": self.get_trend_signal(),
            "macd": self.get_macd_signal(),
            "rsi": self.get_rsi_signal(),
            "kdj": self.get_kdj_signal(),
            "bollinger": self.get_bollinger_signal(),
            "volume": self.get_volume_signal(),
        }
