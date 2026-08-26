"""
输入校验
=======
股票代码格式校验、日期范围校验、参数合法性检查。
"""

import re
from datetime import datetime
from typing import Optional, Tuple


# 沪深股票代码格式
# 沪市主板: 600xxx, 601xxx, 603xxx, 605xxx
# 沪市科创板: 688xxx
# 深市主板: 000xxx, 001xxx
# 深市中小板(已并入主板): 002xxx, 003xxx
# 深市创业板: 300xxx, 301xxx
STOCK_CODE_PATTERN = re.compile(
    r"^(60[0-5]\d{3}|688\d{3}|00[0-3]\d{3}|30[0-1]\d{3})$"
)


def validate_stock_code(code: str) -> Tuple[bool, str]:
    """
    校验股票代码格式

    Args:
        code: 输入的股票代码

    Returns:
        (是否有效, 错误信息)
    """
    code = code.strip()
    if not code:
        return False, "股票代码不能为空"

    if not code.isdigit():
        return False, f"股票代码应为纯数字，当前: {code}"

    if len(code) != 6:
        return False, f"股票代码应为6位数字，当前为{len(code)}位: {code}"

    if not STOCK_CODE_PATTERN.match(code):
        return False, f"股票代码 {code} 不在沪深A股范围内"

    return True, ""


def validate_multiple_codes(codes_str: str) -> Tuple[list, list]:
    """
    校验逗号分隔的多个股票代码

    Args:
        codes_str: 逗号分隔的代码字符串，如 "000001,600519"

    Returns:
        (有效代码列表, 错误信息列表)
    """
    valid_codes = []
    errors = []

    parts = codes_str.replace("，", ",").split(",")
    for part in parts:
        code = part.strip()
        is_valid, msg = validate_stock_code(code)
        if is_valid:
            valid_codes.append(code)
        else:
            errors.append(msg)

    return valid_codes, errors


def validate_date(date_str: str) -> Tuple[bool, str]:
    """
    校验日期格式 YYYYMMDD

    Args:
        date_str: 日期字符串

    Returns:
        (是否有效, 错误信息)
    """
    if not date_str:
        return False, "日期不能为空"

    try:
        datetime.strptime(date_str, "%Y%m%d")
        return True, ""
    except ValueError:
        return False, f"日期格式错误: {date_str}，应为 YYYYMMDD"


def validate_positive_number(value, name: str = "参数") -> Tuple[bool, str]:
    """校验正数"""
    try:
        v = float(value)
        if v <= 0:
            return False, f"{name}应为正数，当前: {value}"
        return True, ""
    except (ValueError, TypeError):
        return False, f"{name}应为有效数字，当前: {value}"


def validate_score_range(value: float, name: str = "评分") -> Tuple[bool, str]:
    """校验评分范围 0-100"""
    if not (0 <= value <= 100):
        return False, f"{name}应在0-100之间，当前: {value}"
    return True, ""
