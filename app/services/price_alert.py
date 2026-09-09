"""
股价预警引擎（v4 P0）—— 自选股价格/涨跌幅/换手/成交额规则 + PushPlus 微信推送
============================================================================
对标 daily_stock_analysis 的 15 种预警，首批落地实时行情可判的 8 种：

  price_above     现价 ≥ 目标价（突破）
  price_below     现价 ≤ 目标价（跌破）
  pct_above       涨跌幅 ≥ X%（如 +5）
  pct_below       涨跌幅 ≤ X%（如 -5）
  amount_above    成交额 ≥ X 亿
  turnover_above  换手率 ≥ X%
  amplitude_above 振幅 ≥ X%
  high_above      盘中最高价 ≥ 目标价

行为：
  - 规则持久化 JSON（cache_data/price_alerts.json）
  - 轮询线程默认 60s 一次，仅交易时段（周一至五 9:15-15:05）
  - 命中 → PushPlus 推送；同规则触发后冷却 30 分钟（防轰炸）
  - 环境变量：MEGOO_ALERT_INTERVAL=60 轮询秒数；WECHAT_PUSHPLUS/PUSHPLUS_TOKEN 推送 token
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger import logger

RULE_FILE = Path(__file__).parent.parent.parent / "cache_data" / "price_alerts.json"
COOLDOWN_MIN = float(os.environ.get("MEGOO_ALERT_COOLDOWN_MIN", "30"))
POLL_SEC = int(os.environ.get("MEGOO_ALERT_INTERVAL", "60"))

RULE_TYPES = {
    "price_above":     "现价 ≥ 目标价",
    "price_below":     "现价 ≤ 目标价",
    "pct_above":       "涨跌幅 ≥ X%",
    "pct_below":       "涨跌幅 ≤ X%",
    "amount_above":    "成交额 ≥ X亿",
    "turnover_above":  "换手率 ≥ X%",
    "amplitude_above": "振幅 ≥ X%",
    "high_above":      "最高价 ≥ 目标价",
}

_lock = threading.Lock()
_last_trigger: Dict[str, float] = {}  # {rule_key: last_sent_ts}
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


# ───────────────────────── 规则存储 ─────────────────────────

def _default_rules() -> List[Dict]:
    return []


def load_rules() -> List[Dict]:
    try:
        if RULE_FILE.exists():
            data = json.loads(RULE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"加载预警规则失败: {e}")
    return _default_rules()


def save_rules(rules: List[Dict]) -> None:
    RULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULE_FILE.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _rule_key(rule: Dict) -> str:
    return f"{rule.get('code','')}:{rule.get('type','')}:{rule.get('value','')}"


def add_rule(code: str, name: str, rule_type: str, value: float,
             enabled: bool = True) -> Dict:
    """新增规则；同 code+type+value 已存在则覆盖 enabled/value"""
    if rule_type not in RULE_TYPES:
        raise ValueError(f"未知规则类型: {rule_type}，可选 {list(RULE_TYPES)}")
    if value <= 0:
        raise ValueError("阈值必须 > 0")
    with _lock:
        rules = load_rules()
        new_rule = {"code": code, "name": name or code, "type": rule_type,
                    "value": float(value), "enabled": bool(enabled),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        key = _rule_key(new_rule)
        for i, r in enumerate(rules):
            if _rule_key(r) == key:
                rules[i] = new_rule
                save_rules(rules)
                return new_rule
        rules.append(new_rule)
        save_rules(rules)
        return new_rule


def remove_rule(code: str, rule_type: str, value: float) -> bool:
    key = f"{code}:{rule_type}:{value}"
    with _lock:
        rules = load_rules()
        remain = [r for r in rules if _rule_key(r) != key]
        if len(remain) == len(rules):
            return False
        save_rules(remain)
        return True


def toggle_rule(code: str, rule_type: str, value: float, enabled: bool) -> bool:
    key = f"{code}:{rule_type}:{value}"
    with _lock:
        rules = load_rules()
        for r in rules:
            if _rule_key(r) == key:
                r["enabled"] = bool(enabled)
                save_rules(rules)
                return True
        return False


# ───────────────────────── 规则判定 ─────────────────────────

def eval_rule(quote, rule: Dict) -> bool:
    """判断单条规则是否命中。quote: StockQuote dataclass"""
    if not quote:
        return False
    t = rule.get("type", "")
    v = float(rule.get("value", 0))
    try:
        if t == "price_above":
            return quote.price >= v
        if t == "price_below":
            return quote.price <= v
        if t == "pct_above":
            return quote.change_pct >= v
        if t == "pct_below":
            return quote.change_pct <= v
        if t == "amount_above":
            return quote.amount / 1e8 >= v
        if t == "turnover_above":
            return quote.turnover >= v
        if t == "amplitude_above":
            return quote.amplitude >= v
        if t == "high_above":
            return quote.high >= v
    except (TypeError, AttributeError) as e:
        logger.warning(f"规则判定异常 {_rule_key(rule)}: {e}")
        return False
    return False


def _rule_desc(rule: Dict) -> str:
    t = rule.get("type", "")
    v = rule.get("value", 0)
    unit = "亿" if t == "amount_above" else "%"
    if t in ("price_above", "price_below", "high_above"):
        unit = "元"
    return f"{RULE_TYPES.get(t, t)} ({v}{unit})"


# ───────────────────────── 推送与轮询 ─────────────────────────

def _push(title: str, content: str) -> bool:
    try:
        from app.services.notify import send_notify
        res = send_notify(title, content)
        return res.get("ok", False)
    except Exception as e:
        logger.warning(f"预警推送异常: {e}")
        return False


def check_once(quotes_map: Dict[str, object]) -> List[Dict]:
    """对给定行情跑全部启用规则，命中则推送（带冷却）。返回命中列表。"""
    hits = []
    now = time.time()
    for rule in load_rules():
        if not rule.get("enabled", True):
            continue
        q = quotes_map.get(str(rule.get("code", "")).zfill(6))
        if q is None:
            continue
        if not eval_rule(q, rule):
            continue
        key = _rule_key(rule)
        last = _last_trigger.get(key, 0)
        if now - last < COOLDOWN_MIN * 60:
            continue
        _last_trigger[key] = now
        hit = {"rule": rule, "quote_price": getattr(q, "price", None),
               "pct": getattr(q, "change_pct", None),
               "time": datetime.now().strftime("%H:%M:%S")}
        hits.append(hit)
        _push(
            f"⚠️ 预警命中：{rule.get('name', rule.get('code'))}",
            f"**{rule.get('name', rule.get('code'))}**（{rule.get('code')}）\n\n"
            f"触发规则：{_rule_desc(rule)}\n\n"
            f"现价 {getattr(q, 'price', '-')} 元　涨跌幅 {getattr(q, 'change_pct', '-')}%\n"
            f"时间：{hit['time']}\n\n"
            f"数据源：实时行情快照（非投资建议）",
        )
    return hits


def _in_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    return 915 <= hm <= 1505


def _poll_loop():
    from data.stock_manager import StockManager
    from data.data_utils import get_best_fetcher
    logger.info(f"🔔 股价预警引擎启动（轮询 {POLL_SEC}s，冷却 {COOLDOWN_MIN:.0f}min）")
    while not _stop.is_set():
        try:
            if _in_trading_time():
                mgr = StockManager(fetcher=get_best_fetcher())
                rows = mgr.get_watchlist_with_quotes()
                quotes_map = {}
                for row in rows:
                    q = row.get("quote")
                    if q is not None:
                        quotes_map[str(row.get("code", "")).zfill(6)] = q
                if quotes_map:
                    check_once(quotes_map)
        except Exception as e:
            logger.warning(f"预警轮询异常: {e}")
        _stop.wait(POLL_SEC)


def start_alert_thread():
    """启动后台轮询线程（幂等：重复调用不重复启动）"""
    global _thread
    if _thread and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_poll_loop, daemon=True, name="price-alert")
    _thread.start()
    return _thread


def stop_alert_thread():
    _stop.set()
