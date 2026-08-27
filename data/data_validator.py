"""
数据校验中间层（v3.1 P0）—— 拦截脏数据，防止"虚假信号"误导
============================================================
文档要求：
  1. 通用校验：价格不能为负、成交额>0、PE/PB 过滤 NaN/无穷/异常极值
  2. 行情集合校验：涨跌家数、涨停/跌停数量合理性区间
  3. 异常标记：每组返回数据打上 is_valid / invalid_reason
  4. 校验不通过不送入分析引擎

用法：
  validate_kline(df)     → 个股K线校验
  validate_valuation(v)  → 估值数据校验
  validate_breadth(d)    → 涨跌家数/涨停跌停校验
"""
import math
from typing import Dict, Optional

import pandas as pd

from utils.logger import logger


def _is_bad_number(v) -> bool:
    """NaN / Inf / 异常极值判断"""
    if v is None:
        return True
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return True
        if abs(f) > 1e15:  # 极端异常值
            return True
        return False
    except (TypeError, ValueError):
        return True


def validate_kline(df) -> Dict:
    """K线数据校验：价格非负、OHLC 逻辑、量能"""
    df = getattr(df, "df", df)
    if df is None or df.empty:
        return {"is_valid": False, "invalid_reason": "K线为空", "data": None}

    problems = []
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            problems.append(f"缺列:{col}")
            continue
        if (df[col] <= 0).any():
            problems.append(f"{col}存在<=0")
        bad = df[col].apply(_is_bad_number)
        if bad.any():
            problems.append(f"{col}存在异常值{int(bad.sum())}个")

    if "volume" in df.columns:
        if (df["volume"] < 0).any():
            problems.append("成交量<0")

    # OHLC 逻辑
    if {"high", "low", "close", "open"}.issubset(df.columns):
        if (df["high"] < df["low"]).any():
            problems.append("high<low")
        if (df["high"] < df["close"]).any():
            problems.append("high<close")

    if problems:
        return {"is_valid": False, "invalid_reason": ";".join(problems[:3]), "data": None}
    return {"is_valid": True, "invalid_reason": "", "data": df}


def validate_valuation(valuation: Dict) -> Dict:
    """估值数据校验：PE/PB 分位范围"""
    if not valuation:
        return {"is_valid": False, "invalid_reason": "估值为空"}
    for key in ("pe_pct", "pb_pct"):
        v = valuation.get(key)
        if v is None:
            continue
        if _is_bad_number(v):
            return {"is_valid": False, "invalid_reason": f"{key}异常值: {v}"}
        if not (0 <= float(v) <= 100):
            return {"is_valid": False, "invalid_reason": f"{key}超出0-100: {v}"}
    return {"is_valid": True, "invalid_reason": ""}


def validate_breadth(activity: Dict) -> Dict:
    """涨跌家数/涨停跌停合理性区间校验"""
    if not activity:
        return {"is_valid": False, "invalid_reason": "活跃度数据为空"}
    up = activity.get("上涨")
    down = activity.get("下跌")
    if up is not None and down is not None:
        try:
            if int(up) + int(down) < 100:
                return {"is_valid": False, "invalid_reason": f"涨跌家数异常(合计<100): {up}+{down}"}
        except (TypeError, ValueError):
            return {"is_valid": False, "invalid_reason": "涨跌家数非数字"}
    lu = activity.get("涨停")
    if lu is not None and not _is_bad_number(lu) and int(lu) > 500:
        return {"is_valid": False, "invalid_reason": f"涨停数异常(>500): {lu}"}
    return {"is_valid": True, "invalid_reason": ""}


def validate_series(values, label: str, min_len: int = 30) -> Dict:
    """时间序列校验（用于资金流/收益率等）"""
    if values is None or len(values) < min_len:
        return {"is_valid": False, "invalid_reason": f"{label}数据不足({len(values) if values is not None else 0}<{min_len})"}
    arr = pd.Series(values).dropna()
    if arr.empty:
        return {"is_valid": False, "invalid_reason": f"{label}全为空"}
    if (arr.abs() > 1e10).any():
        return {"is_valid": False, "invalid_reason": f"{label}存在异常极值"}
    return {"is_valid": True, "invalid_reason": ""}


def safe_analyze(fn, df, validator=validate_kline, **kwargs):
    """安全包装：先校验再分析，不通过直接返回 None（不送入引擎）"""
    check = validator(df)
    if not check["is_valid"]:
        logger.warning(f"数据校验拦截: {check['invalid_reason']}")
        return None
    try:
        return fn(check["data"] if "data" in check else df, **kwargs)
    except Exception as e:
        logger.warning(f"分析失败(已校验): {e}")
        return None
