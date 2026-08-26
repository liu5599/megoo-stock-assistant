"""
测试技术因子和基本面因子
"""
import pytest
import numpy as np
import pandas as pd
from factor_technical import (
    Momentum20Factor, Reversal5Factor, Volatility20Factor,
    Turnover20Factor, VolumePriceCorrFactor, RSIFactor, MADeviationFactor,
)
from factor_fundamental import (
    PEFactor, PBFactor, ROEFactor, RevenueGrowthFactor,
    ProfitGrowthFactor, DebtRatioFactor, GrossMarginFactor,
)


def make_kline(close_values, volume_values=None):
    """创建模拟K线DataFrame"""
    n = len(close_values)
    df = pd.DataFrame({
        "close": close_values,
        "open": [v * 1.001 for v in close_values],
        "high": [v * 1.02 for v in close_values],
        "low": [v * 0.98 for v in close_values],
        "volume": volume_values or [10000.0] * n,
    })
    return df


class TestMomentum20Factor:
    """20日动量因子"""

    def test_positive_momentum(self):
        factor = Momentum20Factor()
        # 股价翻倍
        close = [100 + i * 5 for i in range(30)]
        df = make_kline(close)
        data = {"000001": df}
        result = factor.calculate(data)
        assert result["000001"] > 0  # 上涨→正值

    def test_negative_momentum(self):
        factor = Momentum20Factor()
        # 股价腰斩
        close = [200 - i * 5 for i in range(30)]
        df = make_kline(close)
        data = {"000001": df}
        result = factor.calculate(data)
        assert result["000001"] < 0  # 下跌→负值

    def test_direction_is_positive(self):
        factor = Momentum20Factor()
        assert factor.direction == 1


class TestReversal5Factor:
    """5日反转因子 — 验证符号方向"""

    def test_direction_not_double_negated(self):
        """修正后：direction应为1（calculate已取反）"""
        factor = Reversal5Factor()
        assert factor.direction == 1, (
            f"Reversal5Factor direction应为1（因为calculate()已对收益率取反），"
            f"当前为{factor.direction}"
        )

    def test_stock_that_dropped_gets_high_raw_value(self):
        """跌得多的股票原始值应该高"""
        factor = Reversal5Factor()
        # 5日下跌5%
        close_drop = [100.0 + i * 0.1 for i in range(20)] + [100.0 + 20 * 0.1 - 5.0]
        df_drop = make_kline(close_drop)
        data = {"000001": df_drop}
        result = factor.calculate(data)
        # 原始值应为正值（-(-5) = +5%）
        assert result["000001"] > 0


class TestVolatility20Factor:
    """波动率因子"""

    def test_volatility_positive(self):
        factor = Volatility20Factor()
        close = [100 + np.sin(i) * 5 for i in range(30)]
        df = make_kline(close)
        data = {"000001": df}
        result = factor.calculate(data)
        assert result["000001"] > 0  # 有波动

    def test_direction_is_negative(self):
        factor = Volatility20Factor()
        assert factor.direction == -1  # 低波动得高分


class TestRSIFactor:
    """RSI因子"""

    def test_rsi_in_range(self):
        factor = RSIFactor()
        close = [100 + np.random.randn() * 2 for _ in range(50)]
        df = make_kline(close)
        data = {"000001": df}
        result = factor.calculate(data)
        assert 0 <= result["000001"] <= 100

    def test_direction_is_negative(self):
        factor = RSIFactor()
        assert factor.direction == -1  # 低RSI得高分


class TestMADeviationFactor:
    """均线偏离因子"""

    def test_below_ma_positive_deviation(self):
        """价格低于均线时，偏离为负（负值→反转后得高分）"""
        factor = MADeviationFactor()
        # 前20天稳定在100，最近跌到90
        close = [100.0] * 20 + [95, 93, 90]
        df = make_kline(close)
        data = {"000001": df}
        result = factor.calculate(data)
        assert result["000001"] < 0  # 低于均线，偏离为负


class TestFundamentalFactors:
    """基本面因子"""

    def test_pe_factor_excludes_negative(self):
        factor = PEFactor()
        data = {"000001": {"pe": 15}}
        result = factor.calculate(data)
        assert result["000001"] == -15  # 取负

    def test_pe_factor_negative_pe_is_nan(self):
        factor = PEFactor()
        data = {"000001": {"pe": -5}}
        result = factor.calculate(data)
        assert pd.isna(result["000001"])  # 负PE排除

    def test_roe_factor_direction(self):
        factor = ROEFactor()
        assert factor.direction == 1  # 高ROE高分

    def test_debt_ratio_direction(self):
        factor = DebtRatioFactor()
        assert factor.direction == -1  # 低负债高分

    def test_revenue_growth_direction(self):
        factor = RevenueGrowthFactor()
        assert factor.direction == 1  # 高增长高分
