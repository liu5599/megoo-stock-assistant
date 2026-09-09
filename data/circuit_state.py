"""
熔断状态持久化（v3.1 P1）—— 重启不丢失熔断标记
================================================
各数据源熔断状态写入磁盘（cache_data/circuit_state.json）：
  - 服务重启后加载历史熔断状态，避免"请求风暴"
  - 半开（Half-Open）探测：超过冷却时间自动允许试一次，成功即解除

用法：
  is_open("eastmoney_direct")     → 是否处于熔断
  set_open("eastmoney_direct")    → 触发熔断
  set_closed("eastmoney_direct")  → 解除熔断
"""
import json
import os
import threading
import time
from pathlib import Path

from utils.logger import logger

_STATE_FILE = Path(__file__).parent.parent / "cache_data" / "circuit_state.json"
_COOLDOWN_MIN = 30  # 熔断冷却：30分钟后允许半开探测

_lock = threading.Lock()
_state: dict = {}


def _load():
    global _state
    try:
        if _STATE_FILE.exists():
            _state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"熔断状态加载失败: {e}")
        _state = {}


def _save():
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(_state, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"熔断状态保存失败: {e}")


_load()


def set_open(source: str):
    """触发熔断（记录时间）；只在状态翻转时记日志，避免重复 OPEN 噪声"""
    was_open = _state.get(source, {}).get("open", False)
    with _lock:
        _state[source] = {"open": True, "opened_at": time.time()}
        _save()
    if not was_open:
        from utils.logger import log_event
        log_event("数据源熔断", source=source, action="OPEN")


def set_closed(source: str):
    """解除熔断；只在实际解除(此前处于熔断)时记 CLOSE，成功直连不再刷日志"""
    was_open = _state.get(source, {}).get("open", False)
    with _lock:
        _state.pop(source, None)
        _save()
    if was_open:
        from utils.logger import log_event
        log_event("数据源熔断", source=source, action="CLOSE")


def is_open(source: str) -> bool:
    """
    是否熔断；超过冷却时间 → 半开（允许探测一次，调用方成功后应 set_closed）
    """
    with _lock:
        entry = _state.get(source)
        if not entry or not entry.get("open"):
            return False
        # 半开探测：超过冷却时间，自动解除并允许重试
        if time.time() - entry.get("opened_at", 0) > _COOLDOWN_MIN * 60:
            _state.pop(source, None)
            _save()
            logger.info(f"熔断半开探测: {source} 允许重试")
            return False
        return True


def status() -> dict:
    """熔断状态快照（供 /health 或诊断）"""
    return {k: {"open": v.get("open"), "opened_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v.get("opened_at", 0)))} for k, v in _state.items()}
