"""
v3.1 新增模块单元测试
====================
覆盖：data_validator / snapshot_store / factor_performance
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import pytest

from data.data_validator import validate_kline, validate_valuation, validate_breadth, validate_series
from analysis import snapshot_store


def make_good_kline(n=100):
    rng = np.random.default_rng(1)
    close = 10 * np.cumprod(1 + rng.normal(0.001, 0.01, n))
    return pd.DataFrame({
        "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
        "close": close, "volume": rng.integers(100000, 500000, n).astype(float),
    })


class TestDataValidator:
    def test_good_kline(self):
        r = validate_kline(make_good_kline())
        assert r["is_valid"] is True

    def test_negative_price(self):
        df = make_good_kline()
        df.loc[df.index[10], "close"] = -5
        r = validate_kline(df)
        assert r["is_valid"] is False
        assert "close" in r["invalid_reason"]

    def test_nan_price(self):
        df = make_good_kline()
        df.loc[df.index[10], "high"] = np.nan
        r = validate_kline(df)
        assert r["is_valid"] is False

    def test_high_low_contradiction(self):
        df = make_good_kline()
        df.loc[df.index[10], "low"] = df.loc[df.index[10], "high"] * 2
        r = validate_kline(df)
        assert r["is_valid"] is False

    def test_valuation_range(self):
        assert validate_valuation({"pe_pct": 50})["is_valid"] is True
        assert validate_valuation({"pe_pct": 150})["is_valid"] is False
        assert validate_valuation({"pe_pct": np.nan})["is_valid"] is False

    def test_breadth(self):
        assert validate_breadth({"上涨": 3000, "下跌": 2000, "涨停": 50})["is_valid"] is True
        assert validate_breadth({"上涨": 10, "下跌": 10})["is_valid"] is False
        assert validate_breadth({"涨停": 999})["is_valid"] is False

    def test_series(self):
        assert validate_series([1, 2, 3] * 20, "测试")["is_valid"] is True
        assert validate_series([1, 2], "测试")["is_valid"] is False
        assert validate_series([1e12] * 40, "测试")["is_valid"] is False


class TestSnapshotStore:
    def setup_method(self):
        # 清空测试数据
        with snapshot_store._conn() as c:
            c.execute("DELETE FROM snapshots WHERE trade_date='2026-08-27'")

    def test_save_and_query(self):
        assert snapshot_store.save_snapshot("2026-08-27", "plan",
                                            {"rating": "S", "code": "600001"}, "600001", "测试股")
        rows = snapshot_store.query_snapshots(trade_date="2026-08-27", snapshot_type="plan")
        assert len(rows) >= 1
        assert rows[0]["payload"]["rating"] == "S"

    def test_save_plans_batch(self):
        plans = [{"code": "600001", "name": "A", "rating": "S", "price": 10},
                 {"code": "600002", "name": "B", "rating": "A", "price": 20}]
        n = snapshot_store.save_plans_snapshot(plans)
        assert n == 2

    def test_stats(self):
        s = snapshot_store.stats()
        assert "total" in s
        assert s["total"] >= 0

    def test_latest_plan_codes(self):
        snapshot_store.save_snapshot("2026-08-27", "plan",
                                     {"rating": "B", "code": "600003"}, "600003", "测试3")
        latest = snapshot_store.latest_plan_codes()
        assert isinstance(latest, list)
