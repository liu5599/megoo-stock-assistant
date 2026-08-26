"""
通用辅助函数
===========
日期处理、数值格式化、数据转换等通用工具函数。
"""

from datetime import datetime, timedelta
from typing import Optional


def format_number(value: float, precision: int = 2, unit: str = "") -> str:
    """
    格式化数字显示

    Args:
        value: 数值
        precision: 小数位数
        unit: 单位后缀

    Returns:
        格式化后的字符串
    """
    if abs(value) >= 1e8:
        return f"{value / 1e8:.{precision}f}亿{unit}"
    elif abs(value) >= 1e4:
        return f"{value / 1e4:.{precision}f}万{unit}"
    else:
        return f"{value:.{precision}f}{unit}"


def format_percent(value: float, signed: bool = True) -> str:
    """
    格式化百分比显示

    Args:
        value: 百分比数值（如 5.23 表示 5.23%）
        signed: 是否显示正负号

    Returns:
        格式化后的字符串，如 "+5.23%" 或 "5.23%"
    """
    if signed:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.2f}%"
    return f"{value:.2f}%"


def format_money(value: float) -> str:
    """
    格式化金额显示（自动选择亿/万单位）

    Args:
        value: 金额（元）

    Returns:
        格式化后的字符串
    """
    if abs(value) >= 1e12:
        return f"{value / 1e12:.2f}万亿"
    elif abs(value) >= 1e8:
        return f"{value / 1e8:.2f}亿"
    elif abs(value) >= 1e4:
        return f"{value / 1e4:.2f}万"
    else:
        return f"{value:.2f}"


def get_trading_date_range(days: int = 250) -> tuple:
    """
    获取交易日日期范围（估算，非精确交易日历）

    Args:
        days: 需要的交易日数量

    Returns:
        (start_date, end_date) 格式为 'YYYYMMDD'
    """
    # 交易日约为自然日的1.4倍（含周末节假日）
    calendar_days = int(days * 1.6)
    end = datetime.now()
    start = end - timedelta(days=calendar_days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    安全除法（避免除零错误）

    Args:
        numerator: 分子
        denominator: 分母
        default: 分母为0时的默认返回值

    Returns:
        除法结果
    """
    if denominator == 0:
        return default
    return numerator / denominator


def clamp(value: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """
    将值限制在指定范围内

    Args:
        value: 输入值
        min_val: 最小值
        max_val: 最大值

    Returns:
        限制后的值
    """
    return max(min_val, min(max_val, value))


def get_change_color(value: float) -> str:
    """
    根据涨跌返回对应颜色名

    Args:
        value: 涨跌幅数值

    Returns:
        'red' (上涨), 'green' (下跌), 'white' (平盘)
    """
    if value > 0:
        return "red"
    elif value < 0:
        return "green"
    return "white"


def truncate_string(s: str, max_len: int = 12, suffix: str = "...") -> str:
    """
    截断过长的字符串

    Args:
        s: 原始字符串
        max_len: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的字符串
    """
    if len(s) <= max_len:
        return s
    return s[:max_len - len(suffix)] + suffix
