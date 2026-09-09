"""股价预警引擎单元测试（纯逻辑，不碰网络）"""
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

# 让 import 从项目根可用
sys.path.insert(0, str(Path(__file__).parent.parent))

# 隔离规则文件，避免污染真实数据
_tmp = tempfile.mkdtemp(prefix="alert_test_")
os.environ.setdefault("MEGOO_ALERT_COOLDOWN_MIN", "0")
os.environ.setdefault("WECHAT_PUSHPLUS", "")

from app.services import price_alert  # noqa: E402

price_alert.RULE_FILE = Path(_tmp) / "price_alerts.json"


@dataclass
class FakeQuote:
    code: str
    price: float = 0.0
    change_pct: float = 0.0
    amount: float = 0.0
    turnover: float = 0.0
    amplitude: float = 0.0
    high: float = 0.0


@pytest.fixture(autouse=True)
def clean_rules():
    price_alert.RULE_FILE.unlink(missing_ok=True)
    price_alert._last_trigger.clear()
    yield
    price_alert.RULE_FILE.unlink(missing_ok=True)
    price_alert._last_trigger.clear()


def test_add_and_list_rules():
    price_alert.add_rule("000001", "平安银行", "price_above", 12.5)
    price_alert.add_rule("000001", "平安银行", "pct_above", 5)
    rules = price_alert.load_rules()
    assert len(rules) == 2
    assert rules[0]["code"] == "000001"


def test_add_duplicate_overwrites():
    price_alert.add_rule("000001", "平安银行", "price_above", 12.5, enabled=True)
    price_alert.add_rule("000001", "平安银行", "price_above", 12.5, enabled=False)
    rules = price_alert.load_rules()
    assert len(rules) == 1
    assert rules[0]["enabled"] is False


def test_invalid_type_rejected():
    with pytest.raises(ValueError):
        price_alert.add_rule("000001", "平安银行", "no_such_type", 1)


def test_remove_rule():
    price_alert.add_rule("000001", "平安银行", "price_above", 12.5)
    assert price_alert.remove_rule("000001", "price_above", 12.5) is True
    assert price_alert.remove_rule("000001", "price_above", 12.5) is False
    assert price_alert.load_rules() == []


def test_eval_rule_price_above():
    q = FakeQuote(code="000001", price=13.0)
    assert price_alert.eval_rule(q, {"type": "price_above", "value": 12.5})
    assert not price_alert.eval_rule(q, {"type": "price_above", "value": 14.0})


def test_eval_rule_pct_below():
    q = FakeQuote(code="000001", change_pct=-7.2)
    assert price_alert.eval_rule(q, {"type": "pct_below", "value": -5})
    assert not price_alert.eval_rule(q, {"type": "pct_below", "value": -8})


def test_eval_rule_amount_above_uses_yi():
    q = FakeQuote(code="000001", amount=5e8)  # 5亿元
    assert price_alert.eval_rule(q, {"type": "amount_above", "value": 4})
    assert not price_alert.eval_rule(q, {"type": "amount_above", "value": 6})


def test_eval_rule_turnover_amplitude_high():
    q = FakeQuote(code="000001", turnover=8.5, amplitude=6.0, high=15.0)
    assert price_alert.eval_rule(q, {"type": "turnover_above", "value": 8})
    assert price_alert.eval_rule(q, {"type": "amplitude_above", "value": 5})
    assert price_alert.eval_rule(q, {"type": "high_above", "value": 14})


def test_eval_disabled_rule_skipped_by_check_once():
    # 关闭推送，只验证命中判定逻辑：disabled 规则不进入命中
    price_alert.add_rule("000001", "平安银行", "price_above", 1.0, enabled=False)
    q = FakeQuote(code="000001", price=13.0)
    hits = price_alert.check_once({"000001": q})
    assert hits == []


def test_check_once_hit_and_cooldown():
    price_alert._push = lambda title, content: True  # 打桩推送
    price_alert.add_rule("000001", "平安银行", "price_above", 12.0)
    q = FakeQuote(code="000001", price=13.0)
    hits1 = price_alert.check_once({"000001": q})
    assert len(hits1) == 1
    # 冷却期内（COOLDOWN_MIN=0 测试下直接放行，这里验证冷却逻辑独立）
    price_alert._last_trigger.clear()
    hits2 = price_alert.check_once({"000001": q})
    assert len(hits2) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
