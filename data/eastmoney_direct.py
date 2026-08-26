"""
东方财富直连层 —— 突破免费接口限频
==================================
东财 push2 系列 API 直连（绕过 akshare 的内部限频问题）：
  1. Cookie 预热：先访问东财首页拿 cookie，再带 cookie 请求 API
  2. 域名轮换：push2 / push2his / push2ex 交替，降低单域名触发
  3. 限速：请求间隔 0.6s，批量请求串行
  4. 熔断：连续失败自动降级（调用方有 akshare/Tushare 兜底）

接口清单（clist 通用行情接口）：
  - f62=主力净流入 资金流排行: fid=f62, fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048
  - f3=涨跌幅 通用行情: fid=f3, fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23
字段: f12=代码 f14=名称 f2=最新价 f3=涨跌幅 f62=主力净流入 f184=主力净占比
"""
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from utils.logger import logger

_HOSTS = [
    "https://push2delay.eastmoney.com",   # 备用节点（主节点502时可用，实测有效）
    "https://push2.eastmoney.com",
    "https://push2his.eastmoney.com",
]
_LAST_REQ = 0.0
_MIN_INTERVAL = 0.6  # 限速：请求最小间隔（秒）
_cookie = ""
_circuit_open = False


def _get_session() -> requests.Session:
    """带 Cookie 预热和完整浏览器头的 session（懒初始化）"""
    global _cookie
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    if not _cookie:
        try:
            r = s.get("https://www.eastmoney.com", timeout=6)
            _cookie = "; ".join([f"{c.name}={c.value}" for c in s.cookies])
            logger.info(f"东财 Cookie 预热完成（{len(_cookie)}字符）")
        except Exception as e:
            logger.warning(f"东财 Cookie 预热失败: {e}")
    if _cookie:
        s.headers["Cookie"] = _cookie
    return s


def _throttle():
    """限速：保证请求间隔"""
    global _LAST_REQ
    now = time.time()
    wait = _MIN_INTERVAL - (now - _LAST_REQ)
    if wait > 0:
        time.sleep(wait)
    _LAST_REQ = time.time()


def fetch_clist(fid: str = "f62", fs: str = "", pn: int = 1, pz: int = 100,
                fields: str = "f12,f14,f2,f3,f62,f184") -> Optional[pd.DataFrame]:
    """通用东财行情列表接口（域名轮换 + 限速 + cookie）"""
    global _circuit_open
    if _circuit_open:
        return None

    params = {
        "pn": pn, "pz": pz, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": fid, "fs": fs, "fields": fields, "_": int(time.time() * 1000),
    }
    last_err = ""
    for host in _HOSTS:
        try:
            _throttle()
            s = _get_session()
            r = s.get(f"{host}/api/qt/clist/get", params=params, timeout=10)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                continue
            data = r.json()
            diff = (data.get("data") or {}).get("diff") or []
            if not diff:
                last_err = "空数据"
                continue
            df = pd.DataFrame(diff)
            _circuit_open = False
            return df
        except Exception as e:
            last_err = str(e)[:80]
            logger.warning(f"东财直连失败({host}): {last_err}，换域名...")
            time.sleep(1.0)

    # 全部失败 → 熔断（让调用方走 akshare/Tushare 兜底）
    _circuit_open = True
    logger.warning(f"东财直连熔断开启: {last_err}")
    return None


def reset_circuit():
    """重置熔断（供长时间间隔后恢复尝试）"""
    global _circuit_open
    _circuit_open = False


# ═══════════════════════════════════════════════════════════════
# 业务封装
# ═══════════════════════════════════════════════════════════════

# 全A股资金流排行（f62=主力净流入）
FS_STOCK_FLOW = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
# 全A股行情（f3=涨跌幅）
FS_STOCK_ALL = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def fetch_stock_flow_rank(top_n: int = 100) -> Optional[pd.DataFrame]:
    """全市场主力资金净流入排行（直连，突破限频）"""
    df = fetch_clist(fid="f62", fs=FS_STOCK_FLOW, pz=max(top_n, 100))
    if df is None or df.empty:
        return None
    df = df.rename(columns={"f12": "代码", "f14": "名称", "f2": "最新价",
                            "f3": "今日涨跌幅", "f62": "今日主力净流入-净额",
                            "f184": "今日主力净流入-净占比"})
    for col in ("今日涨跌幅", "今日主力净流入-净额", "今日主力净流入-净占比"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["今日主力净流入-净额"]).sort_values("今日主力净流入-净额", ascending=False)
    return df.head(top_n)


def fetch_stock_quotes(top_n: int = 500) -> Optional[pd.DataFrame]:
    """全市场行情（涨跌幅/最新价）—— 供横截面分析"""
    df = fetch_clist(fid="f3", fs=FS_STOCK_ALL, pz=max(top_n, 100),
                     fields="f12,f14,f2,f3,f20,f21")
    if df is None or df.empty:
        return None
    df = df.rename(columns={"f12": "代码", "f14": "名称", "f2": "最新价",
                            "f3": "涨跌幅", "f20": "总市值", "f21": "流通市值"})
    for col in ("最新价", "涨跌幅", "总市值", "流通市值"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.head(top_n)
