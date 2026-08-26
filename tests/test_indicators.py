"""
测试底层指标计算函数
"""
import pytest
import numpy as np
import pandas as pd
from analysis.indicators import (
    compute_sma, compute_ema, compute_macd, compute_rsi, compute_kdj,
    compute_bollinger, compute_atr, compute_adx, compute_volume_ratio,
    compute_price_momentum, compute_volatility, compute_max_drawdown,
    detect_macd_cross, compute_support_resistance,
    detect_candlestick_patterns, compute_pattern_score,
)


@pytest.fixture
def sample_close():
    """生成100个交易日的模拟收盘价"""
    np.random.seed(42)
    returns = np.random.randn(100) * 0.02
    price = 100 * (1 + returns).cumprod()
    return pd.Series(price, name="close")


@pytest.fixture
def sample_df(sample_close):
    """生成完整的OHLCV模拟数据"""
    n = len(sample_close)
    np.random.seed(42)
    df = pd.DataFrame({
        "close": sample_close.values,
        "open": sample_close.values * (1 + np.random.randn(n) * 0.005),
        "high": sample_close.values * (1 + np.abs(np.random.randn(n) * 0.01)),
        "low": sample_close.values * (1 - np.abs(np.random.randn(n) * 0.01)),
        "volume": np.random.randint(10000, 100000, n).astype(float),
    })
    high = df["high"]
    low = df["low"]
    # 确保 high >= max(open, close) 和 low <= min(open, close)
    for i in range(n):
        o, c = df["open"].iloc[i], df["close"].iloc[i]
        df["high"].iloc[i] = max(df["high"].iloc[i], o, c) + abs(np.random.randn() * 0.5)
        df["low"].iloc[i] = min(df["low"].iloc[i], o, c) - abs(np.random.randn() * 0.5)
    return df, sample_close


class TestMovingAverages:
    """移动均线测试"""

    def test_sma_basic(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_sma(s, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 2.0  # (1+2+3)/3
        assert result.iloc[3] == 3.0  # (2+3+4)/3
        assert result.iloc[4] == 4.0  # (3+4+5)/3

    def test_sma_length(self, sample_close):
        result = compute_sma(sample_close, 20)
        assert len(result) == len(sample_close)

    def test_ema_basic(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_ema(s, 3)
        assert len(result) == len(s)


class TestMACD:
    """MACD测试"""

    def test_macd_output(self, sample_close):
        macd_df = compute_macd(sample_close)
        assert "dif" in macd_df.columns
        assert "dea" in macd_df.columns
        assert "macd" in macd_df.columns
        assert len(macd_df) == len(sample_close)

    def test_macd_cross_detection(self, sample_close):
        macd_df = compute_macd(sample_close)
        crosses = detect_macd_cross(macd_df["dif"], macd_df["dea"])
        assert set(crosses.unique()).issubset({-1, 0, 1})


class TestRSI:
    """RSI测试"""

    def test_rsi_range(self, sample_close):
        rsi = compute_rsi(sample_close, 14)
        assert rsi.min() >= 0
        assert rsi.max() <= 100

    def test_rsi_constant_price(self):
        """价格不变时RSI应为50"""
        constant = pd.Series([100.0] * 50)
        rsi = compute_rsi(constant, 14)
        # 价格不变→涨跌都为零→RSI未定义→返回50
        assert abs(rsi.iloc[-1] - 50) < 5


class TestKDJ:
    """KDJ测试"""

    def test_kdj_output(self, sample_df):
        (df, close) = sample_df
        kdj = compute_kdj(df["high"], df["low"], close)
        assert "k" in kdj.columns
        assert "d" in kdj.columns
        assert "j" in kdj.columns


class TestBollinger:
    """布林带测试"""

    def test_bollinger_output(self, sample_close):
        boll = compute_bollinger(sample_close)
        assert "upper" in boll.columns
        assert "middle" in boll.columns
        assert "lower" in boll.columns
        # 上轨应 > 中轨 > 下轨（最后一行有数据时）
        last_valid = boll.dropna().iloc[-1]
        assert last_valid["upper"] >= last_valid["middle"] >= last_valid["lower"]


class TestATR:
    """ATR测试"""

    def test_atr_positive(self, sample_df):
        (df, close) = sample_df
        atr = compute_atr(df["high"], df["low"], close)
        valid = atr.dropna()
        assert (valid > 0).all()


class TestVolumeRatio:
    """量比测试"""

    def test_volume_ratio(self, sample_df):
        (df, _) = sample_df
        ratio = compute_volume_ratio(df["volume"])
        assert len(ratio) == len(df)


class TestPriceMomentum:
    """价格动量测试"""

    def test_momentum_zero_calc(self):
        """20日前和20日后同价→动量为0"""
        close = pd.Series([100.0] * 30)
        mom = compute_price_momentum(close, 20)
        valid = mom.dropna()
        assert (abs(valid) < 0.01).all()


class TestVolatility:
    """波动率测试"""

    def test_volatility_positive(self, sample_close):
        vol = compute_volatility(sample_close, 20)
        valid = vol.dropna()
        assert (valid >= 0).all()


class TestMaxDrawdown:
    """最大回撤测试"""

    def test_drawdown_values(self, sample_close):
        max_dd, curr_dd, dd_series = compute_max_drawdown(sample_close)
        assert max_dd <= 0  # 回撤为负
        assert len(dd_series) == len(sample_close)

    def test_drawdown_empty(self):
        s = pd.Series([])
        max_dd, _, _ = compute_max_drawdown(s)
        assert pd.isna(max_dd)


class TestSupportResistance:
    """支撑阻力测试"""

    def test_sr_output(self, sample_df):
        (df, close) = sample_df
        support, resistance = compute_support_resistance(close, df["high"], df["low"])
        assert isinstance(support, list)
        assert isinstance(resistance, list)


class TestCandlestickPatterns:
    """K线形态测试"""

    def test_pattern_detection(self):
        """基本形态检测不崩溃"""
        n = 60
        close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.5))
        high = close + np.abs(np.random.randn(n) * 0.5)
        low = close - np.abs(np.random.randn(n) * 0.5)
        open_ = close.shift(1).fillna(100) + np.random.randn(n) * 0.3

        patterns = detect_candlestick_patterns(open_, high, low, close)
        expected_cols = ["hammer", "shooting_star", "doji", "engulfing_bull",
                        "engulfing_bear", "morning_star", "evening_star",
                        "three_white", "three_black", "harami_bull", "harami_bear"]
        for col in expected_cols:
            assert col in patterns.columns

    def test_pattern_score_range(self):
        """形态评分应在[-100, 100]范围内"""
        n = 60
        close = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.5))
        high = close + np.abs(np.random.randn(n) * 0.5)
        low = close - np.abs(np.random.randn(n) * 0.5)
        open_ = close.shift(1).fillna(100) + np.random.randn(n) * 0.3

        patterns = detect_candlestick_patterns(open_, high, low, close)
        score = compute_pattern_score(patterns)
        assert -100 <= score <= 100

    def test_morning_star_uses_intermediate_day(self):
        """验证晨星形态正确使用中间日的body判断"""
        n = 30
        close = pd.Series([100.0] * n)
        high = pd.Series([101.0] * n)
        low = pd.Series([99.0] * n)
        open_ = pd.Series([100.0] * n)

        # 构造晨星形态: Day-2长阴, Day-1小实体, Day-0长阳
        # Day-2: 开盘102, 收盘96(长阴)
        open_.iloc[-3] = 102
        close.iloc[-3] = 96
        high.iloc[-3] = 103
        low.iloc[-3] = 95
        # Day-1: 小实体
        open_.iloc[-2] = 97
        close.iloc[-2] = 98
        high.iloc[-2] = 99
        low.iloc[-2] = 96
        # Day-0: 长阳超过阴线中点
        open_.iloc[-1] = 98
        close.iloc[-1] = 101  # 超过 (102+96)/2 = 99
        high.iloc[-1] = 102
        low.iloc[-1] = 97

        patterns = detect_candlestick_patterns(open_, high, low, close)
        # 晨星应该被检测到
        assert patterns["morning_star"].iloc[-1], "晨星形态应被检测到"
