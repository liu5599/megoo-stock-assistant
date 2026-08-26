"""
测试风控模块
"""
import pytest
import numpy as np
import pandas as pd
from engine.risk_manager import (
    RiskManager, StopLossLevel, TakeProfitLevel, PositionSizing,
    RiskAssessment, SellSignal, StopLossType, TakeProfitType,
)


def make_ohlcv(n=60, start_price=100, trend=0):
    """生成模拟OHLCV数据"""
    np.random.seed(42)
    returns = np.random.randn(n) * 0.02 + trend / n
    close = start_price * (1 + returns).cumprod()
    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    # 修正：确保 high >= close, low <= close
    high = pd.Series([max(h, c) for h, c in zip(high, close)])
    low = pd.Series([min(l, c) for l, c in zip(low, close)])
    volume = pd.Series(np.random.randint(10000, 100000, n), dtype=float)

    df = pd.DataFrame({
        "close": close, "high": high, "low": low, "volume": volume,
        "open": close * (1 + np.random.randn(n) * 0.005),
    })
    return df


class TestRiskManager:
    """风险管理器测试"""

    @pytest.fixture
    def rm(self):
        return RiskManager()

    @pytest.fixture
    def uptrend_df(self):
        return make_ohlcv(100, 100, 0.3)  # 上涨趋势

    @pytest.fixture
    def downtrend_df(self):
        return make_ohlcv(100, 100, -0.3)  # 下跌趋势

    def test_fixed_stop_loss(self, rm):
        sl = rm.calc_fixed_stop(100.0, 0.07)
        assert sl.price == pytest.approx(93.0, 0.01)
        assert sl.distance_pct == 7.0
        assert sl.stop_type == StopLossType.FIXED_PCT

    def test_atr_stop_loss(self, rm, uptrend_df):
        sl = rm.calc_atr_stop(
            uptrend_df["close"], uptrend_df["high"],
            uptrend_df["low"], 100.0
        )
        assert sl.price < 100.0
        assert sl.distance_pct > 0
        assert sl.stop_type == StopLossType.ATR

    def test_ma_stop_loss(self, rm, uptrend_df):
        sl = rm.calc_ma_stop(uptrend_df["close"], 100.0, 60)
        assert sl.price > 0
        assert sl.stop_type == StopLossType.MA

    def test_best_stop_loss_returns_valid(self, rm, uptrend_df):
        current_price = float(uptrend_df["close"].iloc[-1])
        sl = rm.get_best_stop_loss(uptrend_df, current_price)
        assert isinstance(sl, StopLossLevel)
        assert sl.price < current_price

    def test_take_profit(self, rm, uptrend_df):
        current_price = float(uptrend_df["close"].iloc[-1])
        sl = rm.calc_fixed_stop(current_price, 0.07)
        tp = rm.calc_take_profit(uptrend_df, current_price, sl.price)
        assert isinstance(tp, TakeProfitLevel)
        assert tp.price > current_price

    def test_position_sizing(self, rm):
        sl = rm.calc_fixed_stop(100.0, 0.07)
        ps = rm.calc_position_size(100000, 100.0, sl.price)
        assert isinstance(ps, PositionSizing)
        assert ps.suggested_shares >= 100  # 至少一手
        assert ps.position_pct <= 20  # 不超过最大仓位

    def test_assess_stock(self, rm, uptrend_df):
        current_price = float(uptrend_df["close"].iloc[-1])
        risk = rm.assess_stock(uptrend_df, None, current_price)
        assert isinstance(risk, RiskAssessment)
        assert risk.overall_risk_level in ("low", "medium", "high", "extreme")
        assert 0 <= risk.overall_risk_score <= 100

    def test_assess_stock_short_data(self, rm):
        """数据不足时返回高风险"""
        df = make_ohlcv(10)  # 只有10行数据
        risk = rm.assess_stock(df, None, 100.0)
        assert risk.overall_risk_level == "high"
        assert len(risk.warnings) > 0

    def test_sell_signal_detection(self, rm, downtrend_df):
        current_price = float(downtrend_df["close"].iloc[-1])
        signals = rm.detect_sell_signals(downtrend_df, current_price)
        assert isinstance(signals, list)

    def test_sell_signal_with_cost_not_hit(self, rm, uptrend_df):
        """成本价比当前价高很多→应该触发止损信号"""
        current_price = float(uptrend_df["close"].iloc[-1])
        # 成本价远高于当前价 → 亏损
        signals = rm.detect_sell_signals(uptrend_df, current_price, cost_price=current_price * 2)
        # 应该有止损信号（亏损超过7%）
        has_cut_loss = any(s.signal_type == "cut_loss" for s in signals)
        assert has_cut_loss

    def test_no_name_error_in_assess_warning(self, rm, uptrend_df):
        """验证 #update-time 类似bug已修复——warnings中变量名正确"""
        # 强制高波动高回撤
        volatile = make_ohlcv(100, 100, 0.0)
        # 制造大波动
        volatile["close"] = volatile["close"] * (1 + np.sin(np.linspace(0, 10, 100)) * 0.3)
        risk = rm.assess_stock(volatile, None, float(volatile["close"].iloc[-1]))
        # 不应抛出 NameError
        assert isinstance(risk.warnings, list)
        for w in risk.warnings:
            assert isinstance(w, str)
