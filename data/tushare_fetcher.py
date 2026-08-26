"""
Tushare Pro 数据源（付费兜底，可选启用）
========================================
双轨策略：免费源为主，Tushare 为稳定兜底。

启用方式：export TUSHARE_TOKEN=你的token
未配置 TUSHARE_TOKEN 时：所有函数返回 None，系统自动走免费源（不报错、不拖慢）。

覆盖的关键数据（对应免费源痛点）：
  - 个股资金流 moneyflow      → 免费东财 rank 被风控时兜底
  - 涨跌停 limit_list_d       → 免费涨停池不稳定时兜底
  - 龙虎榜 top_list           → 免费东财龙虎榜不稳定时兜底
  - 财经新闻 news             → 新闻维度（免费源基本不可用）

注意：Tushare 数据多为 T+1（收盘后更新），盘中实时仍靠免费源。
"""
import os
import time
from typing import Dict, List, Optional

import pandas as pd

from utils.logger import logger

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
_ts = None
_ts_checked = False


def tushare_enabled() -> bool:
    """是否配置了 Tushare token"""
    return bool(TUSHARE_TOKEN)


def _get_pro():
    """获取 Tushare Pro API（懒加载，未配置返回 None）"""
    global _ts, _ts_checked
    if not TUSHARE_TOKEN:
        return None
    if _ts is None and not _ts_checked:
        try:
            import tushare as ts
            ts.set_token(TUSHARE_TOKEN)
            _ts = ts.pro_api()
            logger.info("✅ Tushare Pro 已启用（付费兜底）")
        except Exception as e:
            logger.warning(f"Tushare 初始化失败: {e}")
        finally:
            _ts_checked = True
    return _ts


def _safe_call(fn, *args, **kwargs):
    """Tushare 调用容错"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Tushare 调用失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# 1. 个股资金流（moneyflow）
# 返回与东财 rank 兼容的 DataFrame：code/name/日期/主力净额等
# ═══════════════════════════════════════════════════════════════

def fetch_moneyflow(trade_date: str = "") -> Optional[pd.DataFrame]:
    """个股资金流（Tushare moneyflow，单日全市场）"""
    pro = _get_pro()
    if pro is None:
        return None
    if not trade_date:
        trade_date = time.strftime("%Y%m%d")
    df = _safe_call(pro.moneyflow, trade_date=trade_date)
    if df is None or df.empty:
        return None
    # 标准化：计算主力净流入 = 大单净额 + 特大单净额
    df["main_net"] = df["buy_lg_amount"] + df["buy_elg_amount"] - df["sell_lg_amount"] - df["sell_elg_amount"]
    df = df.rename(columns={"ts_code": "code", "trade_date": "date"})
    return df


# ═══════════════════════════════════════════════════════════════
# 2. 涨跌停列表（limit_list_d）
# 返回与东财涨停池兼容的结构
# ═══════════════════════════════════════════════════════════════

def fetch_limit_list(trade_date: str = "", limit_type: str = "U") -> Optional[pd.DataFrame]:
    """涨跌停列表（Tushare limit_list_d，U=涨停 D=跌停）"""
    pro = _get_pro()
    if pro is None:
        return None
    if not trade_date:
        trade_date = time.strftime("%Y%m%d")
    df = _safe_call(pro.limit_list_d, trade_date=trade_date, limit_type=limit_type)
    if df is None or df.empty:
        return None
    df = df.rename(columns={"ts_code": "code", "name": "名称"})
    return df


# ═══════════════════════════════════════════════════════════════
# 3. 龙虎榜（top_list）
# ═══════════════════════════════════════════════════════════════

def fetch_top_list(trade_date: str = "") -> Optional[pd.DataFrame]:
    """龙虎榜每日明细（Tushare top_list）"""
    pro = _get_pro()
    if pro is None:
        return None
    if not trade_date:
        trade_date = time.strftime("%Y%m%d")
    df = _safe_call(pro.top_list, trade_date=trade_date)
    if df is None or df.empty:
        return None
    df = df.rename(columns={"ts_code": "code", "name": "名称"})
    return df


# ═══════════════════════════════════════════════════════════════
# 4. 财经新闻（news）
# ═══════════════════════════════════════════════════════════════

def fetch_news(start_date: str = "", end_date: str = "", src: str = "") -> Optional[pd.DataFrame]:
    """财经新闻（Tushare news，需积分）"""
    pro = _get_pro()
    if pro is None:
        return None
    if not end_date:
        end_date = time.strftime("%Y%m%d")
    if not start_date:
        start_date = time.strftime("%Y%m%d", time.localtime(time.time() - 2 * 86400))
    df = _safe_call(pro.news, start_date=start_date, end_date=end_date, src=src)
    return df


# ═══════════════════════════════════════════════════════════════
# 5. 每日估值指标（daily_basic）—— 估值空间模块增强
# 返回兼容东财 stock_value_em 的格式：trade_date/pe_ttm/pb
# ═══════════════════════════════════════════════════════════════

def to_ts_code(code: str) -> str:
    """6位代码 → Tushare 格式（600519→600519.SH，000001→000001.SZ）"""
    code = code.strip()
    if "." in code:
        return code
    if code.startswith(("6", "9", "5")):
        return f"{code}.SH"
    return f"{code}.SZ"


def fetch_daily_basic(ts_code: str = "", trade_date: str = "") -> Optional[pd.DataFrame]:
    """每日估值指标（Tushare daily_basic）
    - ts_code='600519.SH'：单只股票全部历史（估值分位用）
    - trade_date='20260826'：单日全市场
    返回: trade_date/pe_ttm/pb/total_mv/turnover_rate
    """
    pro = _get_pro()
    if pro is None:
        return None
    fields = "ts_code,trade_date,pe_ttm,pb,total_mv,circ_mv,turnover_rate"
    if ts_code:
        df = _safe_call(pro.daily_basic, ts_code=ts_code, fields=fields)
    elif trade_date:
        df = _safe_call(pro.daily_basic, trade_date=trade_date, fields=fields)
    else:
        return None
    if df is None or df.empty:
        return None
    df = df.rename(columns={"ts_code": "code"})
    return df


# ═══════════════════════════════════════════════════════════════
# 便捷：一键检查
# ═══════════════════════════════════════════════════════════════

def status() -> Dict:
    """检查 Tushare 状态"""
    pro = _get_pro()
    if pro is None:
        return {"enabled": False, "msg": "未配置 TUSHARE_TOKEN，走免费源"}
    try:
        df = _safe_call(pro.trade_cal, exchange="SSE", start_date="20260825", end_date="20260825")
        return {"enabled": True, "msg": "Tushare 可用", "sample": len(df) if df is not None else 0}
    except Exception as e:
        return {"enabled": True, "msg": f"Tushare 配置了但调用异常: {e}"}
