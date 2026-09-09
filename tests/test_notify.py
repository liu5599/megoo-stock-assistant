"""统一通知通道测试（mock HTTP，不真发）"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services import notify  # noqa: E402


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("WECHAT_PUSHPLUS", "PUSHPLUS_TOKEN", "WECHAT_WEBHOOK_URL", "FEISHU_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_no_channel_configured():
    res = notify.send_notify("t", "c")
    assert res["ok"] is False
    assert "未配置" in res["msg"]


def test_pushplus_channel_detected(monkeypatch):
    monkeypatch.setenv("WECHAT_PUSHPLUS", "token123")
    assert "pushplus" in notify._channels()


def test_all_channels_detected(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "a")
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://qyapi.weixin.qq.com/x")
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://open.feishu.cn/x")
    assert set(notify._channels()) == {"pushplus", "wecom", "feishu"}


def test_send_pushplus_ok(monkeypatch):
    monkeypatch.setenv("WECHAT_PUSHPLUS", "token123")
    calls = {}

    def fake_post(url, json, timeout):
        calls["url"] = url
        calls["json"] = json
        class R:
            status_code = 200
            text = '{"code":200}'
        return R()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    res = notify.send_notify("标题", "内容")
    assert res["ok"] is True
    assert calls["channels"] if False else "pushplus" in res["channels"]
    assert calls["json"]["token"] == "token123"
    assert calls["url"] == "https://www.pushplus.plus/send"


def test_send_pushplus_fail_body(monkeypatch):
    monkeypatch.setenv("PUSHPLUS_TOKEN", "token123")

    class R:
        status_code = 200
        text = '{"code":500}'

    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: R())
    res = notify.send_notify("t", "c")
    assert res["ok"] is False


def test_send_wecom_ok(monkeypatch):
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "https://qyapi.weixin.qq.com/x")
    calls = {}

    def fake_post(url, json, timeout):
        calls["json"] = json
        class R:
            status_code = 200
            def json(self):
                return {"errcode": 0}
        return R()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    res = notify.send_notify("标题", "正文")
    assert res["ok"] is True
    assert "标题" in calls["json"]["text"]["content"]


def test_send_feishu_ok(monkeypatch):
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://open.feishu.cn/x")
    calls = {}

    def fake_post(url, json, timeout):
        calls["json"] = json
        class R:
            status_code = 200
            def json(self):
                return {"code": 0}
        return R()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    res = notify.send_notify("标题", "正文")
    assert res["ok"] is True
    assert calls["json"]["content"]["text"].startswith("【标题】")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
