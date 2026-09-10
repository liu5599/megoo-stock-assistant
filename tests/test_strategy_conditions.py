"""策略条件引擎测试（表达式求值 + 安全边界，不碰网络）"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis import strategy_conditions as sc  # noqa: E402


ENV = {"close": 105, "MA5": 102, "MA10": 100, "MA20": 98, "MA60": 95,
       "volume": 2000, "VMA5": 1000, "RSI": 65, "pct_chg": 2.5,
       "MACD": 1.2, "MACD_signal": 0.8, "BOLL_up": 110, "BOLL_low": 90}


def test_simple_comparison():
    assert sc.eval_condition("close > MA20", ENV) is True
    assert sc.eval_condition("close < MA20", ENV) is False


def test_arithmetic():
    assert sc.eval_condition("volume > 1.5 * VMA5", ENV) is True
    assert sc.eval_condition("volume > 2.5 * VMA5", ENV) is False


def test_boolean_and_or():
    assert sc.eval_condition("close > MA20 and RSI < 70", ENV) is True
    assert sc.eval_condition("close < MA20 or RSI < 70", ENV) is True
    assert sc.eval_condition("close < MA20 and RSI < 70", ENV) is False


def test_unknown_variable_returns_none():
    assert sc.eval_condition("close > UNKNOWN_VAR", ENV) is None


def test_syntax_error_returns_none():
    assert sc.eval_condition("close >", ENV) is None
    assert sc.eval_condition("", ENV) is None


# ── 安全边界：必须拒绝代码执行 ──

def test_reject_function_call():
    assert sc.eval_condition("__import__('os').system('echo hi')", ENV) is None


def test_reject_attribute_access():
    assert sc.eval_condition("close.__class__", ENV) is None


def test_reject_subscript():
    assert sc.eval_condition("close[0]", ENV) is None


def test_reject_lambda():
    assert sc.eval_condition("(lambda: 1)()", ENV) is None


def test_reject_string_constant():
    assert sc.eval_condition("'abc'", ENV) is None


# ── 条件列表 ──

def test_conditions_all_pass():
    r = sc.eval_conditions(["close > MA20", "RSI < 70"], ENV, mode="all")
    assert r["passed"] is True and r["evaluable"] == 2


def test_conditions_one_fails():
    r = sc.eval_conditions(["close > MA20", "RSI > 90"], ENV, mode="all")
    assert r["passed"] is False


def test_conditions_any_mode():
    r = sc.eval_conditions(["close < MA20", "RSI < 70"], ENV, mode="any")
    assert r["passed"] is True


def test_conditions_no_evaluable():
    r = sc.eval_conditions(["FOO > 1"], ENV, mode="all")
    assert r["passed"] is False and r["evaluable"] == 0


# ── 策略命中 ──

def test_check_strategy_entry_hit():
    strat = {"entry_conditions": ["close > MA20", "RSI < 70"],
             "exit_conditions": ["close < MA10"]}
    r = sc.check_strategy(strat, ENV)
    assert r["hit"] == "entry"


def test_check_strategy_exit_hit():
    env2 = dict(ENV, close=95)  # 跌破 MA10
    strat = {"entry_conditions": ["close > MA20"],
             "exit_conditions": ["close < MA10"]}
    r = sc.check_strategy(strat, env2)
    assert r["hit"] == "exit"


def test_check_strategy_no_hit():
    # entry 不满足(close<MA20) 且 exit 不满足(close>MA10) → 无命中
    env = {"close": 99.0, "MA20": 100.0, "MA10": 95.0}
    strat = {"entry_conditions": ["close > MA20"],
             "exit_conditions": ["close < MA10"]}
    r = sc.check_strategy(strat, env)
    assert r["hit"] is None


def test_real_strategy_yaml_loads_conditions():
    """真实 strategies/*.yaml 的条件能被求值（不是只有话术）"""
    from app.services import ask_agent
    strategies = ask_agent.load_strategies()
    comp = strategies["comprehensive"]
    assert "entry_conditions" in comp and comp["entry_conditions"]
    r = sc.check_strategy(comp, ENV)
    assert r["entry"]["total"] == len(comp["entry_conditions"])
    assert r["entry"]["evaluable"] >= 1  # 至少能判定一个（变量都提供）


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
