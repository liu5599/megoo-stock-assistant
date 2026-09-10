"""风控委员会 + 结构化决策测试（纯逻辑，不碰网络）"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services import risk_manager, ask_agent  # noqa: E402


# ───────── 风控委员会 ─────────

def _buy(**kw):
    d = {"code": "600519", "name": "贵州茅台", "action": "buy",
         "price": 100.0, "stop_loss": 90.0, "position_ratio": 0.1}
    d.update(kw)
    return d


def test_normal_buy_approved():
    r = risk_manager.check(_buy(), portfolio={}, market={})
    assert r["approved"] is True
    assert r["position_ratio"] == 0.1


def test_r4_no_stop_loss_veto():
    r = risk_manager.check(_buy(stop_loss=None), {})
    assert r["approved"] is False
    assert any("R4" in v for v in r["vetoes"])


def test_r4_stop_above_price_veto():
    r = risk_manager.check(_buy(stop_loss=110.0), {})
    assert r["approved"] is False
    assert any("R4" in v for v in r["vetoes"])


def test_r1_total_position_veto():
    r = risk_manager.check(_buy(), portfolio={"total_position": 0.95})
    assert r["approved"] is False
    assert any("R1" in v for v in r["vetoes"])


def test_r2_concentration_veto():
    r = risk_manager.check(_buy(), portfolio={"positions": {"600519": {"ratio": 0.25}}})
    assert r["approved"] is False
    assert any("R2" in v for v in r["vetoes"])


def test_r2_concentration_trim():
    # 已占 15%，再加 10% 超 20% → 缩至 5%，不否决
    r = risk_manager.check(_buy(position_ratio=0.10),
                           portfolio={"positions": {"600519": {"ratio": 0.15}}})
    assert r["approved"] is True
    assert any("R2" in a for a in r["adjustments"])
    assert abs(r["position_ratio"] - 0.05) < 1e-6


def test_r3_defensive_regime_cap():
    r = risk_manager.check(_buy(position_ratio=0.5), market={"regime": "防守"})
    assert r["approved"] is True
    assert any("R3" in a for a in r["adjustments"])
    assert r["position_ratio"] <= 0.10


def test_r5_single_trade_risk_cap():
    # 止损距离 20%（100→80），仓位 20% → 风险 4% > 2% → 缩至 10%
    r = risk_manager.check(_buy(position_ratio=0.20, stop_loss=80.0), {})
    assert r["approved"] is True
    assert any("R5" in a for a in r["adjustments"])
    assert r["position_ratio"] <= 0.1001


def test_sell_not_blocked():
    r = risk_manager.check({"action": "sell", "code": "600519"}, {})
    assert r["approved"] is True  # 卖出/减仓放行


def test_veto_zeroes_position():
    r = risk_manager.check(_buy(), {"total_position": 0.95})
    assert r["position_ratio"] == 0.0


# ───────── 结构化决策 ─────────

def test_parse_json_loose_plain():
    assert ask_agent._parse_json_loose('{"action":"buy"}')["action"] == "buy"


def test_parse_json_loose_markdown():
    txt = '```json\n{"action":"sell","confidence":0.8}\n```'
    r = ask_agent._parse_json_loose(txt)
    assert r["action"] == "sell"


def test_parse_json_loose_with_prefix():
    txt = '这是我的判断：{"action":"hold"} 完毕'
    assert ask_agent._parse_json_loose(txt)["action"] == "hold"


def test_parse_json_loose_invalid():
    assert ask_agent._parse_json_loose("没有JSON") is None


def test_norm_ratio_decimal():
    assert ask_agent._norm_ratio(0.2, None) == 0.2


def test_norm_ratio_percent():
    assert abs(ask_agent._norm_ratio(20, None) - 0.2) < 1e-9


def test_norm_ratio_fallback_pct():
    assert abs(ask_agent._norm_ratio(None, 30) - 0.30) < 1e-9


def test_decision_from_plan_buy():
    d = ask_agent._decision_from_plan(
        {"action": "买入", "price": 100, "stop_loss": 90, "target_price": 120,
         "position_pct": 25, "rating": "A"}, "测试票")
    assert d["action"] == "buy"
    assert abs(d["position_ratio"] - 0.25) < 1e-9


def test_decide_end_to_end_no_llm(monkeypatch):
    # mock 数据装配，走确定性决策 + 风控
    monkeypatch.setattr(ask_agent, "_collect_stock_data", lambda code: {
        "code": code, "name": "贵州茅台", "price": 100.0,
        "plan": {"rating": "A", "action": "买入", "price": 100.0, "stop_loss": 90.0,
                 "target_price": 120.0, "position_pct": 20, "entry_low": 98, "entry_high": 101},
        "decision": {"long_term": {"signal": "多"}, "swing": {"signal": "多"},
                     "short_term": {"signal": "多"}, "composite_score": 80, "action": "买入"},
    })
    res = ask_agent.decide("600519", with_llm=False)
    assert res["executed"]["approved"] is True
    assert res["executed"]["action"] == "buy"
    assert res["decision"]["stop_loss"] == 90.0


def test_decide_vetoed_by_risk(monkeypatch):
    monkeypatch.setattr(ask_agent, "_collect_stock_data", lambda code: {
        "code": code, "name": "贵州茅台", "price": 100.0,
        "plan": {"rating": "A", "action": "买入", "price": 100.0, "stop_loss": 90.0,
                 "target_price": 120.0, "position_pct": 20},
        "decision": {},
    })
    # 总仓位 95% → 风控否决
    res = ask_agent.decide("600519", with_llm=False,
                           portfolio={"total_position": 0.95})
    assert res["executed"]["approved"] is False
    assert res["executed"]["action"] == "hold"
    assert res["executed"]["position_ratio"] == 0.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
