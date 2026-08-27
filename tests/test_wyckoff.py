"""
威科夫吸筹引擎单元测试
====================
覆盖：区间识别 / Spring检测 / SOS检测 / 量价评分 / 阶段判定
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import pytest

from analysis.wyckoff import WyckoffAnalyzer, analyze_wyckoff


def make_kline(n=200, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-08-25", periods=n)
    close = 10 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, n)))
    volume = rng.integers(100000, 500000, n).astype(float)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": volume})


def make_accumulation_kline(n=150):
    """横盘吸筹形态：先下跌后低位横盘缩量，最后一天跌破下沿收回（Spring）"""
    rng = np.random.default_rng(11)
    dates = pd.bdate_range(end="2026-08-25", periods=n)
    base = 10
    # 前50日下跌，后100日横盘 9.5-10.5 缩量
    close = np.concatenate([
        np.linspace(12, 10, 50),
        10 + rng.normal(0, 0.12, 100),
    ])
    # 最后一天 Spring：低点跌破 9.5，收盘收回区间内（>下沿）
    close[-1] = 10.1
    low = np.minimum(close - 0.1, close) * 0.995
    low[-1] = 9.3  # 跌破下沿
    high = np.maximum(close + 0.1, close) * 1.005
    open_ = close * 0.995
    volume = np.concatenate([rng.integers(500000, 800000, 50).astype(float),
                             rng.integers(100000, 250000, 100).astype(float)])
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": volume})


class TestWyckoff:
    def test_analyze_basic(self):
        result = WyckoffAnalyzer().analyze(make_kline())
        assert "phase" in result
        assert "accumulation_score" in result
        assert "spring_signal" in result
        assert "sos_signal" in result
        assert 0 <= result["accumulation_score"] <= 100

    def test_spring_detection(self):
        """Spring 形态 → 检测到抄底信号"""
        result = WyckoffAnalyzer().analyze(make_accumulation_kline())
        assert result["spring_signal"] is True
        assert result["accumulation_score"] >= 60
        assert "弹簧" in result["reason"]

    def test_sos_detection(self):
        """放量突破 → SOS 信号（v3.1 降噪：需非下跌趋势）"""
        df = make_kline(150)
        # 构造上涨趋势（降噪后下跌趋势中 SOS 无效）
        trend = np.linspace(0.9, 1.15, len(df))
        for col in ("close", "high", "low", "open"):
            df[col] = df[col] * trend
        # 构造放量突破：最后3日放量 + 价格高于区间上沿
        zone = WyckoffAnalyzer().analyze(df)
        df2 = df.copy()
        zone_high = zone["zone_high"]
        df2.loc[df2.index[-3:], "close"] = zone_high * 1.05
        df2.loc[df2.index[-3:], "high"] = zone_high * 1.06
        df2.loc[df2.index[-3:], "volume"] = df2["volume"].mean() * 1.8
        result = WyckoffAnalyzer().analyze(df2)
        assert result["sos_signal"] is True

    def test_volume_price_score(self):
        """放量下跌 → 低分；缩量横盘 → 高分"""
        ana = WyckoffAnalyzer()
        df = make_kline(60)
        # 放量下跌
        df1 = df.copy()
        df1.loc[df1.index[-5:], "close"] = df1["close"].iloc[-6] * np.linspace(0.99, 0.95, 5)
        df1.loc[df1.index[-5:], "volume"] = df1["volume"].mean() * 1.8
        s1 = ana._volume_price_score(df1.tail(30))
        # 缩量横盘
        df2 = df.copy()
        df2.loc[df2.index[-5:], "close"] = df2["close"].iloc[-6] * np.linspace(1.0, 1.01, 5)
        df2.loc[df2.index[-5:], "volume"] = df2["volume"].mean() * 0.5
        s2 = ana._volume_price_score(df2.tail(30))
        assert s1 < 40
        assert s2 >= 60

    def test_phase_logic(self):
        ana = WyckoffAnalyzer()
        assert ana._phase(85, 9.5, 9.4, 10.5, False) == "吸筹完成/拉升前夜"
        assert ana._phase(70, 10.0, 9.4, 10.5, True) == "拉升初期"
        assert ana._phase(30, 9.0, 9.4, 10.5, False) == "下跌/未知"

    def test_insufficient_data(self):
        result = WyckoffAnalyzer().analyze(make_kline(30))
        assert result["phase"] == "未知"
