"""
告警中心（v3.1 P0）—— 基于 PushPlus 的系统故障微信告警
========================================================
触发条件：
  1. 核心数据源熔断（东财直连/资金流/涨停池）
  2. 数据校验失败（data_validator 拦截）
  3. 关键模块返回空数据（温度计/题材/资金）

特性：
  - 分级：P0 严重（熔断/核心数据断供）｜P1 警告（校验失败）｜P2 提示
  - 节流：同事件 30 分钟只发一次（避免消息轰炸）
  - 环境变量：MEGOO_ALERT_PUSHPLUS_ENABLE=true 开启
"""
import os
import threading
import time
from typing import Dict, Optional

import requests

from utils.logger import logger

PUSHPLUS_TOKEN = os.environ.get("WECHAT_PUSHPLUS", "")
ENABLED = os.environ.get("MEGOO_ALERT_PUSHPLUS_ENABLE", "true").lower() != "false"

# 节流：{event_key: last_sent_ts}
_throttle: Dict[str, float] = {}
_lock = threading.Lock()
_THROTTLE_MIN = 30  # 同事件 30 分钟只发一次


def _should_send(event_key: str) -> bool:
    now = time.time()
    with _lock:
        last = _throttle.get(event_key, 0)
        if now - last < _THROTTLE_MIN * 60:
            return False
        _throttle[event_key] = now
        return True


def send_alert(title: str, content: str, level: str = "P1", event_key: str = "") -> bool:
    """发送告警（PushPlus）。同 event_key 30 分钟内只发一次。"""
    if not ENABLED or not PUSHPLUS_TOKEN:
        return False
    if event_key and not _should_send(event_key):
        return False

    try:
        resp = requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": f"[{level}] {title}",
                "content": content,
                "template": "markdown",
            },
            timeout=10,
        )
        ok = resp.status_code == 200 and '"code":200' in resp.text
        if ok:
            logger.info(f"告警已发送: [{level}] {title}")
        else:
            logger.warning(f"告警发送失败: {resp.text[:100]}")
            from utils.logger import log_event
            log_event("告警", level=level, status="FAIL", msg=resp.text[:100])
        return ok
    except Exception as e:
        logger.warning(f"告警发送异常: {e}")
        from utils.logger import log_event
        log_event("告警", level=level, status="ERROR", msg=str(e))
        return False


# ═══════════════════════════════════════════════════════════════
# 具体告警场景
# ═══════════════════════════════════════════════════════════════

def alert_circuit_break(source: str):
    """数据源熔断告警（P0）"""
    send_alert(
        f"数据源熔断: {source}",
        f"**{source}** 连续失败触发熔断，后续请求已自动降级。\n\n"
        f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"影响：相关数据可能延迟或使用备用源",
        level="P0", event_key=f"circuit:{source}",
    )


def alert_data_invalid(module: str, reason: str):
    """数据校验失败告警（P1）"""
    send_alert(
        f"数据校验拦截: {module}",
        f"**{module}** 数据校验未通过：{reason}\n\n"
        f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"影响：该数据未送入分析引擎",
        level="P1", event_key=f"invalid:{module}",
    )


def alert_empty_data(module: str):
    """关键模块空数据告警（P1）"""
    send_alert(
        f"关键模块空数据: {module}",
        f"**{module}** 返回空数据，操盘台对应区域将显示为空。\n\n"
        f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"建议：检查数据源状态或稍后刷新",
        level="P1", event_key=f"empty:{module}",
    )


def alert_stale_data(module: str, age_min: float):
    """数据过期告警（P1）"""
    send_alert(
        f"数据过期: {module}",
        f"**{module}** 数据已过期 **{age_min:.0f} 分钟**，超过阈值。\n\n"
        f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"建议：检查数据源或手动刷新",
        level="P1", event_key=f"stale:{module}",
    )
