"""盘面定性引擎 + 题材阶段模型 单测"""
import pandas as pd
import pytest

from analysis.market_regime import compute_regime
from analysis.theme_center import theme_stage, zt_stats_for_board


# ── 盘面定性（真操盘手阈值） ──

def test_regime_attack_on_strong_breadth():
    """79涨停0跌停+主力流入 → 进攻（修复'温度55却叫中性'误判的核心场景）"""
    today = {"上涨": 3212, "下跌": 1875, "涨停": 79, "真实涨停": 69, "跌停": 0, "平盘": 120}
    bb = {"net_total": 247.12}
    r = compute_regime(today, bb)
    assert r["regime"] == "进攻"
    assert r["position_max"] == 0.7


def test_regime_attack_without_money_data():
    """主力数据缺失不阻塞进攻判定"""
    today = {"上涨": 3212, "下跌": 1875, "涨停": 79, "跌停": 0}
    assert compute_regime(today, {})["regime"] == "进攻"


def test_regime_attack_but_net_outflow_downgrades_position():
    """涨停多但主力净流出 → 进攻定性但仓位压到5成"""
    today = {"上涨": 2600, "下跌": 1400, "涨停": 60, "跌停": 2}
    r = compute_regime(today, {"net_total": -80.0})
    assert r["regime"] == "进攻"
    assert r["position_max"] == 0.5


def test_regime_ice_cold_on_crash():
    crash = {"上涨": 300, "下跌": 4800, "涨停": 15, "跌停": 320, "平盘": 30}
    r = compute_regime(crash, {})
    assert r["regime"] == "冰点"
    assert r["position_max"] == 0.1


def test_regime_defensive_on_loss_effect():
    weak = {"上涨": 900, "下跌": 4200, "涨停": 20, "跌停": 45, "平盘": 30}
    assert compute_regime(weak, {})["regime"] == "防守"


def test_regime_mania_on_limit_up_flood():
    mania = {"上涨": 4500, "下跌": 400, "涨停": 160, "跌停": 3, "平盘": 20}
    r = compute_regime(mania, {})
    assert r["regime"] == "过热"
    assert r["position_max"] == 0.5  # 亢奋不满仓


def test_regime_unknown_when_no_data():
    """数据不足 → 未知，绝不当真实判断"""
    r = compute_regime({}, {})
    assert r["regime"] == "未知"
    assert r["reasons"]


# ── 题材阶段 ──

def test_theme_stage_rules():
    assert theme_stage(0, 0) == ""
    assert theme_stage(3, 1) == "启动"      # 零星首板
    assert theme_stage(6, 1) == "发酵"      # 首板潮
    assert theme_stage(3, 2) == "发酵"      # 出现2板
    assert theme_stage(6, 2) == "主升"      # 2板+梯队量
    assert theme_stage(3, 3) == "主升"      # 3板龙头
    assert theme_stage(3, 5) == "高潮"      # 5板+ 亢奋


def _fake_zt():
    return pd.DataFrame([
        {"代码": "600001", "名称": "亚盛集团", "所属行业": "种植业", "连板数": 4, "封板资金": 3e8},
        {"代码": "600002", "名称": "北大荒", "所属行业": "种植业", "连板数": 1, "封板资金": 1e8},
        {"代码": "600003", "名称": "苏垦农发", "所属行业": "农产品加工", "连板数": 1, "封板资金": 2e8},
        {"代码": "600004", "名称": "某芯片股", "所属行业": "半导体", "连板数": 2, "封板资金": 5e8},
    ])


def test_zt_stats_matches_concept_via_mapping():
    """玉米(概念) → 种植业/农产品加工 涨停聚类（修复直等匹配≈0 bug）"""
    st = zt_stats_for_board("玉米", _fake_zt())
    assert st is not None
    assert st["limit_up_count"] == 3
    assert st["highest_board"] == 4
    assert st["leader"] == "亚盛集团"
    assert st["ladder"].get("4板") == 1


def test_zt_stats_semiconductor_direct():
    st = zt_stats_for_board("半导体", _fake_zt())
    assert st is not None and st["limit_up_count"] == 1


def test_zt_stats_no_match_returns_none():
    assert zt_stats_for_board("不存在的概念", _fake_zt()) is None
