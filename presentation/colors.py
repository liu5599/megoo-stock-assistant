"""
统一颜色方案
===========
定义终端输出的统一配色，遵循A股习惯：
- 红色 = 上涨 / 买入 / 利好
- 绿色 = 下跌 / 卖出 / 利空
- 黄色 = 中性 / 持有 / 观望
- 灰色 = 次要信息
"""

from rich.style import Style
from rich.color import Color

# ======================== 基础颜色定义 ========================

# 涨跌色（A股习惯：红涨绿跌）
COLOR_UP = "#FF3333"        # 上涨红
COLOR_DOWN = "#33CC33"      # 下跌绿
COLOR_FLAT = "#999999"      # 平盘灰

# 建议色
COLOR_STRONG_BUY = "#FF0044"   # 强烈买入（深红）
COLOR_BUY = "#FF6666"          # 买入（浅红）
COLOR_HOLD = "#FFCC00"         # 持有观望（金黄）
COLOR_SELL = "#66CC66"         # 卖出（浅绿）
COLOR_STRONG_SELL = "#00AA00"  # 强烈卖出（深绿）

# 功能色
COLOR_PRIMARY = "#3388FF"      # 主色调（蓝）
COLOR_SECONDARY = "#AAAAAA"    # 次要文字
COLOR_HIGHLIGHT = "#FFB800"    # 高亮（金色）
COLOR_WARNING = "#FF6600"      # 警告（橙）
COLOR_DANGER = "#FF0000"       # 危险（红）
COLOR_SUCCESS = "#00CC66"      # 成功（绿）
COLOR_INFO = "#66CCFF"         # 信息（浅蓝）

# 评分色阶
COLOR_SCORE_HIGH = "#FF3333"    # 高分 (80-100)
COLOR_SCORE_GOOD = "#FF8844"    # 良好 (65-80)
COLOR_SCORE_MID = "#FFCC00"     # 中等 (45-65)
COLOR_SCORE_LOW = "#88CC44"     # 偏低 (30-45)
COLOR_SCORE_BAD = "#33AA33"     # 差 (0-30)

# ======================== Rich Style 对象 ========================

# 涨跌风格
STYLE_UP = Style(color=COLOR_UP)
STYLE_DOWN = Style(color=COLOR_DOWN)
STYLE_FLAT = Style(color=COLOR_FLAT)

# 建议风格
STYLE_STRONG_BUY = Style(color=COLOR_STRONG_BUY, bold=True)
STYLE_BUY = Style(color=COLOR_BUY)
STYLE_HOLD = Style(color=COLOR_HOLD)
STYLE_SELL = Style(color=COLOR_SELL)
STYLE_STRONG_SELL = Style(color=COLOR_STRONG_SELL, bold=True)

# 功能风格
STYLE_PRIMARY = Style(color=COLOR_PRIMARY, bold=True)
STYLE_SECONDARY = Style(color=COLOR_SECONDARY)
STYLE_WARNING = Style(color=COLOR_WARNING)
STYLE_DANGER = Style(color=COLOR_DANGER, bold=True)

# 标题风格
STYLE_TITLE = Style(color="#FFFFFF", bold=True)
STYLE_SUBTITLE = Style(color=COLOR_SECONDARY)

# ======================== 辅助函数 ========================

def get_score_color(score: float) -> str:
    """
    根据评分返回对应颜色

    Args:
        score: 0-100评分

    Returns:
        颜色hex字符串
    """
    if score >= 80:
        return COLOR_SCORE_HIGH
    elif score >= 65:
        return COLOR_SCORE_GOOD
    elif score >= 45:
        return COLOR_SCORE_MID
    elif score >= 30:
        return COLOR_SCORE_LOW
    return COLOR_SCORE_BAD


def get_change_style(change_pct: float) -> Style:
    """
    根据涨跌幅返回对应Rich Style

    Args:
        change_pct: 涨跌幅百分比

    Returns:
        Rich Style对象
    """
    if change_pct > 0:
        return STYLE_UP
    elif change_pct < 0:
        return STYLE_DOWN
    return STYLE_FLAT


def get_recommendation_style(recommendation: str) -> Style:
    """
    根据建议等级返回对应Style

    Args:
        recommendation: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'

    Returns:
        Rich Style对象
    """
    styles = {
        "STRONG_BUY": STYLE_STRONG_BUY,
        "BUY": STYLE_BUY,
        "HOLD": STYLE_HOLD,
        "SELL": STYLE_SELL,
        "STRONG_SELL": STYLE_STRONG_SELL,
    }
    return styles.get(recommendation, STYLE_FLAT)
