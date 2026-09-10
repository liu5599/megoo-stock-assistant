"""AI 问股引擎测试（策略加载/路由/模板诊断，不碰 LLM 与行情网络）"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DEEPSEEK_API_KEY", "")

from app.services import ask_agent  # noqa: E402


def test_strategies_loaded():
    strategies = ask_agent.load_strategies()
    assert "comprehensive" in strategies
    assert "wyckoff" in strategies
    assert "instructions" in strategies["comprehensive"]
    assert "aliases" in strategies["wyckoff"]


def test_resolve_strategy_by_alias():
    s = ask_agent.resolve_strategy("用威科夫看看主力建仓")
    assert s.get("name") == "wyckoff"


def test_resolve_strategy_default():
    s = ask_agent.resolve_strategy("随便看看")
    assert s.get("name") == "comprehensive"


def test_resolve_explicit_strategy_name():
    s = ask_agent.resolve_strategy("wyckoff")
    assert s.get("name") == "wyckoff"


def test_resolve_strategy_empty():
    strategies = ask_agent.load_strategies()
    assert ask_agent.resolve_strategy("") == strategies.get("comprehensive")


def test_summarize_empty_data():
    assert ask_agent._summarize_data({}) == "（无数据）"
    assert ask_agent._summarize_data({"error": "boom"}) == "数据获取失败: boom"


def test_summarize_includes_capital_flow_and_news():
    detail = {
        "code": "600519", "name": "贵州茅台", "price": 1290.88,
        "capital_flow": {"main_net_inflow_wan": 50000.0, "main_inflow_ratio": 3.5},
        "recent_news": [{"title": "茅台业绩预增"}, {"title": "白酒板块回暖"}],
    }
    s = ask_agent._summarize_data(detail)
    assert "资金面" in s and "5.00亿" in s
    assert "近期新闻" in s and "茅台业绩预增" in s


def test_summarize_without_capital_flow_ok():
    s = ask_agent._summarize_data({"code": "600519", "name": "茅台", "price": 100.0})
    assert "资金面" not in s  # 无数据不硬编


def test_fallback_answer_no_llm():
    detail = {
        "code": "600519", "name": "贵州茅台", "price": 1290.88,
        "decision": {"long_term": {"signal": "多"}, "swing": {"signal": "多"},
                     "short_term": {"signal": "观望"}, "composite_score": 75, "action": "买入"},
        "plan": {"rating": "A", "action": "买入", "entry_low": 1250, "entry_high": 1280,
                 "target_price": 1400, "stop_loss": 1200, "position_pct": 30},
        "valuation": {"pe_pct": 40, "pb_pct": 50, "zone_cn": "价值中枢区"},
    }
    ans = ask_agent._fallback_answer(detail)
    assert "A" in ans and "买入" in ans
    assert "非投资建议" in ans


def test_ask_deterministic_without_key(monkeypatch):
    monkeypatch.setattr(ask_agent, "_collect_stock_data",
                        lambda code: {"code": "600519", "name": "贵州茅台", "price": 1290.88,
                                      "plan": {"rating": "A", "action": "买入",
                                               "entry_low": 1250, "entry_high": 1280,
                                               "target_price": 1400, "stop_loss": 1200,
                                               "position_pct": 30}})
    result = ask_agent.ask("600519", question="威科夫分析", with_llm=False)
    assert result["deterministic"] is True
    assert result["strategy"] == "威科夫吸筹"
    assert "贵州茅台" in result["answer"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
