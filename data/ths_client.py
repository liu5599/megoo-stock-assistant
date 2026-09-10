"""同花顺 Financial-API 客户端（REST, fuyao.aicubes.cn）
========================================================
独立工具模块：按需为 megoo 数据链路提供稳定兜底（东财/腾讯挂掉时）。
能力：历史日K(前/后/不复权)、实时快照、涨停池(含连板/原因)。
不继承 DataFetcher 抽象（只暴露调用点需要的函数），Key 读 HITHINK_FINANCE_API_KEY。

契约：GET + Header X-api-key；业务信封 code==0；thscode 需带交易所后缀。
"""
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
import requests

from data.models import KLineData, StockQuote
from utils.logger import logger

_BASE = "https://fuyao.aicubes.cn"
_CST = timezone(timedelta(hours=8))
_session = requests.Session()
_session.headers.update({"User-Agent": "megoo-stock-assistant/1.0"})


def api_key() -> str:
    return os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()


def available() -> bool:
    return bool(api_key())


class ThsError(Exception):
    pass


def _to_thscode(code: str) -> Optional[str]:
    """6位代码 → 完整 thscode；指数/板块(BJ)不在本模块支持范围返回 None"""
    code = code.strip()
    if not code.isdigit() or len(code) != 6:
        return None
    if code.startswith(("4", "8", "92")):
        return None  # 北交所暂不接
    return f"{code}.SH" if code.startswith(("5", "6", "9")) else f"{code}.SZ"


def _get(path: str, params: Dict, retries: int = 2) -> dict:
    key = api_key()
    if not key:
        raise ThsError("未配置 HITHINK_FINANCE_API_KEY")
    last = None
    for i in range(retries + 1):
        try:
            r = _session.get(_BASE + path, params=params, headers={"X-api-key": key}, timeout=15)
            d = r.json()
            code = d.get("code")
            if code == 0:
                return d.get("data") or {}
            if code in (1001, 1002, 1003, 1004, 2001, 2003, 3001, 3004):
                raise ThsError(f"THS {code}: {d.get('message')}")
            last = ThsError(f"THS {code}: {d.get('message')}")
        except ThsError:
            raise
        except Exception as e:
            last = e
        if i < retries:
            time.sleep(0.8 * (i + 1))
    raise ThsError(f"THS 请求失败: {last}")


def _cst_day_ms(day: str = "") -> int:
    if not day:
        day = datetime.now(_CST).strftime("%Y-%m-%d")
    day = day.strip()
    if len(day) == 8 and day.isdigit():
        day = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
    dt = datetime.strptime(day[:10], "%Y-%m-%d").replace(tzinfo=_CST)
    return int(dt.timestamp() * 1000)


def _day_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=_CST).strftime("%Y-%m-%d")


# ───────────────────────── 历史日K ─────────────────────────

def ths_history_kline(
    code: str, start_date: str = "", end_date: str = "",
    adjust: str = "qfq",
) -> Optional[KLineData]:
    """日K（THS 仅支持 1d；周/月线返回 None 由上层继续降级）。
    volume 返回股 → 转手(/100) 与 EM/baostock 对齐。
    """
    thscode = _to_thscode(code)
    if not thscode:
        return None
    end = end_date or datetime.now(_CST).strftime("%Y%m%d")
    start = start_date or (datetime.now(_CST) - timedelta(days=400)).strftime("%Y%m%d")
    adj_map = {"": "none", "qfq": "forward", "hfq": "backward"}
    data = _get("/api/a-share/prices/historical", {
        "thscode": thscode, "interval": "1d",
        "start": _cst_day_ms(start), "end": _cst_day_ms(end),
        "adjust": adj_map.get(adjust, "forward"),
    })
    items = data.get("item") or []
    if not items:
        return None
    rows = []
    prev_close = None
    for b in items:
        close = float(b["close_price"])
        chg = (close / prev_close - 1) * 100 if prev_close else 0.0
        rows.append({
            "date": _day_str(b["date_ms"]),
            "open": float(b["open_price"]), "close": close,
            "high": float(b["high_price"]), "low": float(b["low_price"]),
            "volume": float(b.get("volume") or 0) / 100,  # 股 → 手
            "amount": float(b.get("turnover") or 0),
            "change_pct": round(chg, 2),
        })
        prev_close = close
    df = pd.DataFrame(rows)
    return KLineData(code=code, name=code, df=df, period="daily", adjust=adjust)


# ───────────────────────── 实时快照 ─────────────────────────

def ths_snapshot_quotes(codes: List[str]) -> Dict[str, StockQuote]:
    """快照不含中文名(需要时由上层 name 缓存补)。"""
    result: Dict[str, StockQuote] = {}
    valid = [c for c in codes if _to_thscode(c)]
    if not valid:
        return result
    for i in range(0, len(valid), 40):
        batch = valid[i:i + 40]
        ths_codes = [t for c in batch for t in [_to_thscode(c)] if t]
        if not ths_codes:
            continue
        data = _get("/api/a-share/prices/snapshot", {
            "thscodes": ",".join(ths_codes),
        })
        for it in data.get("item") or []:
            ticker = it.get("ticker") or ""
            if not ticker:
                continue
            result[ticker] = StockQuote(
                code=ticker, name=ticker, price=float(it.get("last_price") or 0),
                change_pct=float(it.get("price_change_ratio_pct") or 0),
                change_amount=0.0, amplitude=0.0,
                open=float(it.get("open_price") or 0),
                high=float(it.get("high_price") or 0),
                low=float(it.get("low_price") or 0),
                pre_close=float(it.get("prev_price") or 0),
                volume=float(it.get("volume") or 0) / 100,
                amount=float(it.get("turnover") or 0),
                turnover=0.0,
            )
    return result


# ───────────────────────── 涨停池 ─────────────────────────

def ths_limit_up_pool(day: str = "", size: int = 200) -> Optional[pd.DataFrame]:
    """当日涨停/连板池 → megoo 兼容列(代码/名称/涨跌幅/连板数/封板资金/所属行业/涨停原因)。
    所属行业 THS 未提供，留空由上游聚类模块自行兜底。
    """
    rows_all = []
    page = 1
    while True:
        data = _get("/api/a-share/special-data/limit-up-pool", {
            "date_ms": _cst_day_ms(day), "page": page, "size": 100,
            "sort_field": "continue_day_cnt", "sort_dir": "desc",
        })
        items = data.get("item") or []
        if not items:
            break
        for it in items:
            rows_all.append({
                "代码": it.get("ticker"), "名称": it.get("name"),
                "涨跌幅": float(it.get("price_change_ratio_pct") or 0),
                "连板数": int(it.get("continue_day_cnt") or 1),
                "封板资金": float(it.get("seal_money") or 0),
                "所属行业": "",
                "涨停原因": it.get("limit_up_reason") or "",
            })
        total = (data.get("pagination") or {}).get("total") or 0
        if page * 100 >= total or len(rows_all) >= size:
            break
        page += 1
    if not rows_all:
        return None
    df = pd.DataFrame(rows_all)
    return df.head(size) if size and len(df) > size else df


if __name__ == "__main__":
    # 自检：有 Key 时跑最小真实请求
    assert available(), "未配置 HITHINK_FINANCE_API_KEY"
    k = ths_history_kline("600519", "20260801", "20260909", "qfq")
    print("kline rows:", 0 if k is None or k.df is None else len(k.df))
    pool = ths_limit_up_pool("2026-09-09", size=5)
    print("pool:", None if pool is None else pool[["代码", "名称", "连板数"]].to_dict("records"))
