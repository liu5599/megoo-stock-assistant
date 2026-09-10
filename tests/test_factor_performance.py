"""决策账本算法测试（T+N 交易日 / MFE/MAE / 待观察，mock K线不碰网络）"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis import factor_performance as fp  # noqa: E402
from data.models import KLineData  # noqa: E402


def _kline(dates, closes, highs=None, lows=None):
    highs = highs or closes
    lows = lows or closes
    df = pd.DataFrame({
        "date": dates, "open": closes, "close": closes,
        "high": highs, "low": lows, "volume": [100] * len(dates),
    })
    return KLineData(code="600519", df=df, period="daily", adjust="qfq")


class FakeFetcher:
    def __init__(self, kline):
        self._kl = kline

    def get_history_kline(self, *a, **k):
        return self._kl


@pytest.fixture
def patch_deps(monkeypatch):
    def _setup(rows, kline):
        monkeypatch.setattr(fp.snapshot_store, "query_snapshots",
                            lambda **k: rows)
        monkeypatch.setattr("data.data_utils.get_best_fetcher",
                            lambda *a, **k: FakeFetcher(kline))
    return _setup


def _row(code="600519", rating="A", snap="2026-08-01", price=100.0,
         target=120.0, stop=90.0):
    return {"trade_date": snap, "code": code, "name": "测试",
            "payload": {"rating": rating, "price": price, "target_price": target,
                        "stop_loss": stop, "action": "买入"}}


def test_tn_return_uses_snapshot_day_not_now(patch_deps):
    # 快照日 08-01，其后交易日共 5 天，T+3 收盘 = 105 → 收益 +5%
    dates = ["2026-07-30", "2026-07-31", "2026-08-01",
             "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]
    closes = [98, 99, 100, 102, 103, 105, 108]
    patch_deps([_row(snap="2026-08-01", price=100.0)], _kline(dates, closes))
    r = fp.FactorPerformance(horizon_days=3).evaluate_plans()
    assert r["available"] is True
    assert abs(r["ratings"]["A"]["avg_return"] - 5.0) < 1e-6  # 105/100-1


def test_pending_when_not_enough_days(patch_deps):
    dates = ["2026-08-01", "2026-08-04", "2026-08-05"]
    closes = [100, 101, 102]
    patch_deps([_row(snap="2026-08-01")], _kline(dates, closes))
    r = fp.FactorPerformance(horizon_days=5).evaluate_plans()  # 需 T+5，只有 2 天后数据
    assert r["available"] is False
    assert r["pending"] == 1


def test_mfe_mae(patch_deps):
    dates = ["2026-08-01", "2026-08-04", "2026-08-05", "2026-08-06"]
    closes = [100, 101, 99, 103]
    highs = [100, 112, 105, 103]   # 区间最高 112 → MFE +12%
    lows = [100, 101, 92, 95]      # 区间最低 92 → MAE -8%
    patch_deps([_row(snap="2026-08-01", price=100.0)], _kline(dates, closes, highs, lows))
    r = fp.FactorPerformance(horizon_days=3).evaluate_plans()
    assert r["ratings"]["A"]["avg_mfe"] == 12.0
    assert r["ratings"]["A"]["avg_mae"] == -8.0


def test_hit_stop_first(patch_deps):
    dates = ["2026-08-01", "2026-08-04", "2026-08-05", "2026-08-06"]
    closes = [100, 88, 95, 100]  # 08-04 收 88 < 止损 90 → 先止损
    patch_deps([_row(snap="2026-08-01", stop=90.0, target=120.0)],
               _kline(dates, closes))
    r = fp.FactorPerformance(horizon_days=3).evaluate_plans()
    assert r["ratings"]["A"]["hit_stop"] == 1
    assert r["ratings"]["A"]["hit_target"] == 0


def test_hit_target_first(patch_deps):
    dates = ["2026-08-01", "2026-08-04", "2026-08-05", "2026-08-06"]
    closes = [100, 125, 118, 121]  # 08-04 收 125 > 目标 120 → 先目标
    patch_deps([_row(snap="2026-08-01", stop=90.0, target=120.0)],
               _kline(dates, closes))
    r = fp.FactorPerformance(horizon_days=3).evaluate_plans()
    assert r["ratings"]["A"]["hit_target"] == 1


def test_reproducible_same_result_twice(patch_deps):
    """同一样本回看两次结果一致（修复前 T+now 不可复现）"""
    dates = ["2026-08-01", "2026-08-04", "2026-08-05", "2026-08-06"]
    closes = [100, 102, 103, 105]
    patch_deps([_row(snap="2026-08-01")], _kline(dates, closes))
    a = fp.FactorPerformance(horizon_days=3).evaluate_plans()
    b = fp.FactorPerformance(horizon_days=3).evaluate_plans()
    assert a["ratings"] == b["ratings"]


def test_no_snapshots(patch_deps):
    patch_deps([], _kline(["2026-08-01"], [100]))
    r = fp.FactorPerformance().evaluate_plans()
    assert r["available"] is False
    assert "无快照" in r["msg"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
