"""AI 复盘反思测试（mock 数据源，不碰网络/LLM）"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services import reflection  # noqa: E402


def _samples():
    return [
        {"trade_date": "2026-09-01", "code": "600001", "name": "甲", "rating": "A",
         "action": "买入", "base_price": 10.0, "close_now": 8.0, "return_pct": -20.0},
        {"trade_date": "2026-09-01", "code": "600002", "name": "乙", "rating": "S",
         "action": "买入", "base_price": 20.0, "close_now": 21.0, "return_pct": 5.0},
        {"trade_date": "2026-09-02", "code": "600003", "name": "丙", "rating": "C",
         "action": "观望", "base_price": 5.0, "close_now": 5.5, "return_pct": 10.0},
    ]


def test_pick_lessons_stats():
    lessons = reflection._pick_lessons(_samples())
    assert lessons["stats"]["buy_count"] == 2
    assert lessons["stats"]["buy_win_rate"] == 50.0
    assert lessons["stats"]["buy_avg_return"] == -7.5


def test_pick_lessons_worst_first():
    lessons = reflection._pick_lessons(_samples())
    assert lessons["worst_buys"][0]["code"] == "600001"  # 亏损最多排最前
    assert lessons["worst_sa"][0]["code"] == "600001"


def test_reflect_no_samples(monkeypatch):
    monkeypatch.setattr(reflection, "_evaluate_snapshots", lambda **kw: [])
    r = reflection.reflect(with_llm=False)
    assert r["available"] is False
    assert "无历史计划快照" in r["msg"]


def test_reflect_deterministic_writes_file(monkeypatch, tmp_path):
    monkeypatch.setattr(reflection, "_evaluate_snapshots", lambda **kw: _samples())
    monkeypatch.setattr(reflection, "REFLECTION_FILE", tmp_path / "reflection.md")
    monkeypatch.setattr(reflection, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(reflection, "DEEPSEEK_API_KEY", "")
    r = reflection.reflect(with_llm=False)
    assert r["available"] is True
    assert "确定性复盘" in r["reflection"]
    assert (tmp_path / "reflection.md").exists()
    content = (tmp_path / "reflection.md").read_text(encoding="utf-8")
    assert "AI 复盘反思" in content
    assert "买入胜率" in content or "胜率" in content


def test_load_reflection_roundtrip(monkeypatch, tmp_path):
    f = tmp_path / "reflection.md"
    f.write_text("测试反思内容", encoding="utf-8")
    monkeypatch.setattr(reflection, "REFLECTION_FILE", f)
    assert reflection.load_reflection() == "测试反思内容"


def test_load_reflection_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(reflection, "REFLECTION_FILE", tmp_path / "nope.md")
    assert reflection.load_reflection() == ""


def test_reflection_context_injection(monkeypatch):
    from app.services import ask_agent
    monkeypatch.setattr(reflection, "load_reflection", lambda: "历史教训：别追高")
    ctx = ask_agent._reflection_context()
    assert "历史复盘教训" in ctx
    assert "别追高" in ctx


def test_reflection_context_empty(monkeypatch):
    from app.services import ask_agent
    monkeypatch.setattr(reflection, "load_reflection", lambda: "")
    assert ask_agent._reflection_context() == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
