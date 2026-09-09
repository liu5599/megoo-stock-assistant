"""
统一通知通道（v4 P1）—— PushPlus + 企业微信 + 飞书 webhook
====================================================================
替代三处重复的 PushPlus 直连（daily_report / alert_center / price_alert）。
按环境变量启用通道，全部发一遍（任一成功即 ok）：
  - PushPlus:  WECHAT_PUSHPLUS 或 PUSHPLUS_TOKEN
  - 企业微信:   WECHAT_WEBHOOK_URL
  - 飞书:       FEISHU_WEBHOOK_URL
"""
import os
from typing import Dict, List

import requests

import utils.logger as _log

logger = _log.logger


def _channels() -> List[str]:
    """按已配置 token 返回启用通道"""
    ch = []
    if os.environ.get("WECHAT_PUSHPLUS") or os.environ.get("PUSHPLUS_TOKEN"):
        ch.append("pushplus")
    if os.environ.get("WECHAT_WEBHOOK_URL"):
        ch.append("wecom")
    if os.environ.get("FEISHU_WEBHOOK_URL"):
        ch.append("feishu")
    return ch


def _send_pushplus(title: str, content: str) -> bool:
    token = os.environ.get("WECHAT_PUSHPLUS") or os.environ.get("PUSHPLUS_TOKEN", "")
    try:
        resp = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content,
                  "template": "markdown"},
            timeout=10,
        )
        ok = resp.status_code == 200 and '"code":200' in resp.text
        if not ok:
            logger.warning(f"PushPlus 失败: {resp.text[:100]}")
        return ok
    except Exception as e:
        logger.warning(f"PushPlus 异常: {e}")
        return False


def _send_wecom(title: str, content: str) -> bool:
    """企业微信机器人 webhook（markdown 用 text 兼容）"""
    url = os.environ.get("WECHAT_WEBHOOK_URL", "")
    try:
        # 企微 webhook 的 markdown 对标题敏感，统一用 text + 标题行
        text = f"【{title}】\n{content}"
        resp = requests.post(url, json={"msgtype": "text", "text": {"content": text[:4000]}},
                             timeout=10)
        ok = resp.status_code == 200 and resp.json().get("errcode") == 0
        if not ok:
            logger.warning(f"企业微信失败: {resp.text[:100]}")
        return ok
    except Exception as e:
        logger.warning(f"企业微信异常: {e}")
        return False


def _send_feishu(title: str, content: str) -> bool:
    url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    try:
        resp = requests.post(url, json={
            "msg_type": "text",
            "content": {"text": f"【{title}】\n{content[:4000]}"},
        }, timeout=10)
        ok = resp.status_code == 200 and resp.json().get("code") == 0
        if not ok:
            logger.warning(f"飞书失败: {resp.text[:100]}")
        return ok
    except Exception as e:
        logger.warning(f"飞书异常: {e}")
        return False


def send_notify(title: str, content: str) -> Dict:
    """群发全部已配置通道。返回 {ok, channels:[成功列表], failed:[失败列表]}"""
    channels = _channels()
    if not channels:
        return {"ok": False, "msg": "未配置任何通知通道（WECHAT_PUSHPLUS / WECHAT_WEBHOOK_URL / FEISHU_WEBHOOK_URL）",
                "channels": [], "failed": []}
    ok_list, fail_list = [], []
    senders = {
        "pushplus": _send_pushplus,
        "wecom": _send_wecom,
        "feishu": _send_feishu,
    }
    for ch in channels:
        try:
            if senders[ch](title, content):
                ok_list.append(ch)
            else:
                fail_list.append(ch)
        except Exception as e:
            logger.warning(f"通知通道 {ch} 异常: {e}")
            fail_list.append(ch)
    return {"ok": bool(ok_list), "channels": ok_list, "failed": fail_list,
            "msg": f"成功:{ok_list} 失败:{fail_list}" if fail_list else ""}
