"""
交易计划引擎单元测试
====================
覆盖：评级 / 操作 / 止损止盈 / 仓位 / 组合层
全部使用 mock 数据，不依赖真实网络。
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import pytest

from analysis.trade_planner import TradePlanner, plan_stock
from analysis.decision_signals import DecisionSignals


def make_uptrend_kline(n=450):
    """强上升趋势 K 线"""
    rng = np.random.default_rng(7)
    close = 10 * np.cumprod(1 + rng.normal(0.003, 0.015, n))
    return pd.DataFrame({
        "date": pd.bdate_range(end="2026-08-25", periods=n),
        "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
        "close": close,
        "volume": rng.integers(200000, 800000, n).astype(float),
    })


def make_downtrend_kline(n=450):
    """强下降趋势 K 线"""
    rng = np.random.default_rng(8)
    close = 100 * np.cumprod(1 - rng.normal(0.002, 0.015, n))
    return pd.DataFrame({
        "date": pd.bdate_range(end="2026-08-25", periods=n),
        "open": close * 1.01, "high": close * 1.02, "low": close * 0.98,
        "close": close,
        "volume": rng.integers(200000, 800000, n).astype(float),
    })


def make_decision(score=70, lt="多", sw="多", st="多"):
    return {
        "composite_score": score,
        "long_term": {"signal": lt, "score": 70, "reason": "周线多头排列"},
        "swing": {"signal": sw, "score": 65, "reason": "MACD金叉"},
        "short_term": {"signal": st, "score": 60, "reason": "5日动量偏多"},
    }


class TestTradePlanner:
    def setup_method(self):
        self.planner = TradePlanner(total_capital=1_000_000, risk_per_trade=0.02)

    def test_rate_s(self):
        """两维做多 + 综合≥70 + 估值中枢 → S级"""
        assert self.planner._rate(make_decision(72, "多", "多", "观望"),
                                  {"zone": "价值中枢区"}) == "S"

    def test_rate_a(self):
        assert self.planner._rate(make_decision(62, "多", "观望", "观望"),
                                  {"zone": "价值中枢区"}) == "A"

    def test_rate_c_downtrend(self):
        """两维做空 → C级"""
        assert self.planner._rate(make_decision(35, "空", "空", "观望"),
                                  {"zone": "价值中枢区"}) == "C"

    def test_rate_c_warn_zone(self):
        """估值风险警戒区 → C级（无论信号多强）"""
        assert self.planner._rate(make_decision(80, "多", "多", "多"),
                                  {"zone": "风险警戒区"}) == "C"

    def test_plan_uptrend(self):
        """上升趋势 → 完整交易计划字段"""
        df = make_uptrend_kline()
        decision = DecisionSignals().comprehensive(df)
        plan = self.planner.plan("600519", "测试股", df, decision, {"zone": "价值中枢区"})

        assert plan["rating"] in ("S", "A", "B", "C")
        assert plan["action"] in ("买入/加仓", "买入", "持有/试仓", "卖出/回避", "观望")
        assert plan["entry_low"] <= plan["entry_high"]
        assert plan["target_price"] > plan["price"] or plan["rating"] == "C"
        assert plan["stop_loss"] < plan["price"]
        assert 0 < plan["position_pct"] <= 20
        assert plan["position_shares"] % 100 == 0  # A股按手
        assert plan["logic"] and plan["risks"]
        assert plan["holding_period"] in ("中线（4-12周）", "波段（1-4周）", "短线（3-10日）", "观望")

    def test_plan_downtrend(self):
        """下降趋势 → 评级C/卖出回避"""
        df = make_downtrend_kline()
        decision = DecisionSignals().comprehensive(df)
        plan = self.planner.plan("000001", "测试股", df, decision, {"zone": "价值中枢区"})
        assert plan["rating"] == "C"
        assert plan["action"] in ("卖出/回避", "观望")

    def test_risk_amount(self):
        """单笔风险 = 总资金 × 2%"""
        plan = self.planner.plan("600519", "测试股", make_uptrend_kline(),
                                 make_decision(70, "多", "多", "多"), {"zone": "价值中枢区"})
        assert plan["risk_amount"] == 20000

    def test_portfolio_position(self):
        assert "60-80%" in TradePlanner.portfolio_position("安全边界区")["total_position"]
        assert "20-40%" in TradePlanner.portfolio_position("风险警戒区")["total_position"]
        assert "40-60%" in TradePlanner.portfolio_position("价值中枢区")["total_position"]
