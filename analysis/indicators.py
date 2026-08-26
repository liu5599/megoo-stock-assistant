"""
底层指标计算函数
===============
纯数学函数，不依赖外部状态，便于单元测试。
所有函数接受pandas Series / DataFrame，返回计算结果。

包含指标：
  - 移动均线 (MA/SMA/EMA)
  - MACD (指数平滑异同移动平均线)
  - RSI (相对强弱指标)
  - KDJ (随机指标)
  - 布林带 (Bollinger Bands)
  - ATR (平均真实波幅)
  - ADX (平均趋向指数)
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional


# ======================== 移动均线 ========================

def compute_sma(series: pd.Series, period: int) -> pd.Series:
    """
    计算简单移动均线 (SMA)

    Args:
        series: 价格序列（通常用收盘价）
        period: 均线周期

    Returns:
        SMA序列
    """
    return series.rolling(window=period, min_periods=period).mean()


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """
    计算指数移动均线 (EMA)

    Args:
        series: 价格序列
        period: 均线周期

    Returns:
        EMA序列
    """
    return series.ewm(span=period, adjust=False).mean()


def compute_multi_ma(close: pd.Series, periods: list) -> pd.DataFrame:
    """
    批量计算多周期移动均线

    Args:
        close: 收盘价序列
        periods: 周期列表，如 [5, 10, 20, 60, 120]

    Returns:
        DataFrame，列名格式为 'ma5', 'ma10' 等
    """
    df = pd.DataFrame(index=close.index)
    for p in periods:
        df[f"ma{p}"] = compute_sma(close, p)
    return df


# ======================== MACD ========================

def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26,
                 signal: int = 9) -> pd.DataFrame:
    """
    计算MACD指标

    Args:
        close: 收盘价序列
        fast: 快线周期（默认12）
        slow: 慢线周期（默认26）
        signal: 信号线周期（默认9）

    Returns:
        DataFrame with columns: 'dif', 'dea', 'macd' (柱状图)
    """
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)

    dif = ema_fast - ema_slow
    dea = compute_ema(dif, signal)
    macd_bar = 2 * (dif - dea)  # MACD柱状图（国内常用2倍）

    return pd.DataFrame({
        "dif": dif,
        "dea": dea,
        "macd": macd_bar,
    }, index=close.index)


def detect_macd_cross(dif: pd.Series, dea: pd.Series) -> pd.Series:
    """
    检测MACD金叉/死叉

    Args:
        dif: DIF序列
        dea: DEA序列

    Returns:
        信号序列: 1=金叉, -1=死叉, 0=无信号
    """
    cross = pd.Series(0, index=dif.index)

    # 前一日DIF <= DEA，当日DIF > DEA → 金叉
    prev_dif = dif.shift(1)
    prev_dea = dea.shift(1)

    golden = (prev_dif <= prev_dea) & (dif > dea)
    death = (prev_dif >= prev_dea) & (dif < dea)

    cross[golden] = 1
    cross[death] = -1
    return cross


# ======================== RSI ========================

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    计算RSI相对强弱指标

    Args:
        close: 收盘价序列
        period: 计算周期（默认14）

    Returns:
        RSI序列 (0-100)
    """
    delta = close.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50)  # 初始值设为中性50

    return rsi.clip(0, 100)


# ======================== KDJ ========================

def compute_kdj(high: pd.Series, low: pd.Series, close: pd.Series,
                n: int = 9, k_period: int = 3, d_period: int = 3) -> pd.DataFrame:
    """
    计算KDJ随机指标

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        n: RSV周期（默认9）
        k_period: K值平滑周期（默认3）
        d_period: D值平滑周期（默认3）

    Returns:
        DataFrame with columns: 'k', 'd', 'j'
    """
    # 计算N日内最低价和最高价
    lowest_low = low.rolling(window=n, min_periods=n).min()
    highest_high = high.rolling(window=n, min_periods=n).max()

    # RSV (Raw Stochastic Value)
    rsv = ((close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)) * 100
    rsv = rsv.fillna(50)

    # 计算K、D、J值
    k = rsv.ewm(alpha=1 / k_period, adjust=False).mean()
    d = k.ewm(alpha=1 / d_period, adjust=False).mean()
    j = 3 * k - 2 * d

    return pd.DataFrame({"k": k, "d": d, "j": j}, index=close.index)


# ======================== 布林带 ========================

def compute_bollinger(close: pd.Series, period: int = 20,
                      std_dev: int = 2) -> pd.DataFrame:
    """
    计算布林带 (Bollinger Bands)

    Args:
        close: 收盘价序列
        period: 中轨周期（默认20）
        std_dev: 标准差倍数（默认2）

    Returns:
        DataFrame with columns: 'upper', 'middle', 'lower', 'bandwidth', 'percent_b'
    """
    middle = compute_sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()

    upper = middle + std_dev * std
    lower = middle - std_dev * std

    # 带宽 (bandwidth) = (upper - lower) / middle * 100
    bandwidth = ((upper - lower) / middle.replace(0, np.nan)) * 100

    # %b = (close - lower) / (upper - lower)
    percent_b = ((close - lower) / (upper - lower).replace(0, np.nan))

    return pd.DataFrame({
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
        "percent_b": percent_b,
    }, index=close.index)


# ======================== ATR ========================

def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = 14) -> pd.Series:
    """
    计算ATR平均真实波幅

    Args:
        high: 最高价
        low: 最低价
        close: 收盘价
        period: 计算周期

    Returns:
        ATR序列
    """
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / period, adjust=False).mean()

    return atr


# ======================== ADX ========================

def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = 14) -> pd.DataFrame:
    """
    计算ADX平均趋向指数

    Args:
        high: 最高价
        low: 最低价
        close: 收盘价
        period: 计算周期

    Returns:
        DataFrame with columns: 'adx', 'plus_di', 'minus_di'
    """
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # 真实波幅
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # 方向运动
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # 平滑
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)

    # ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    return pd.DataFrame({
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
    }, index=close.index)


# ======================== 其他指标 ========================

def compute_volume_ma(volume: pd.Series, period: int = 20) -> pd.Series:
    """计算成交量均线"""
    return compute_sma(volume, period)


def compute_volume_ratio(volume: pd.Series, period: int = 5) -> pd.Series:
    """
    计算量比（当日成交量 / 过去N日均量）

    Args:
        volume: 成交量序列
        period: 均量周期

    Returns:
        量比序列
    """
    avg_volume = compute_sma(volume.shift(1), period)
    return volume / avg_volume.replace(0, np.nan)


def compute_price_momentum(close: pd.Series, period: int = 20) -> pd.Series:
    """
    计算价格动量（N日涨跌幅 %）

    Args:
        close: 收盘价序列
        period: 周期

    Returns:
        动量序列（%）
    """
    return (close / close.shift(period) - 1) * 100


def compute_volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """
    计算历史波动率（年化）

    Args:
        close: 收盘价序列
        period: 计算窗口

    Returns:
        年化波动率序列
    """
    log_returns = np.log(close / close.shift(1))
    rolling_std = log_returns.rolling(window=period, min_periods=period).std()
    # 年化：日波动率 * sqrt(252)
    return rolling_std * np.sqrt(252) * 100


def compute_max_drawdown(close: pd.Series) -> Tuple[float, float, pd.Series]:
    """
    计算最大回撤

    Args:
        close: 收盘价序列

    Returns:
        (最大回撤%, 当前回撤%, 回撤序列)
    """
    if close.empty:
        return float("nan"), float("nan"), pd.Series(dtype=float)
    cumulative_max = close.expanding().max()
    drawdown = (close - cumulative_max) / cumulative_max * 100
    max_dd = drawdown.min()
    current_dd = drawdown.iloc[-1]
    return max_dd, current_dd, drawdown


# ======================== K线形态识别 ========================

def detect_candlestick_patterns(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.DataFrame:
    """
    识别常见K线形态

    检测的形态：
      - hammer: 锤子线（底部反转信号）
      - shooting_star: 射击之星（顶部反转信号）
      - engulfing_bull: 阳包阴（看涨吞没）
      - engulfing_bear: 阴包阳（看跌吞没）
      - doji: 十字星（趋势犹豫）
      - harami_bull: 看涨孕线
      - harami_bear: 看跌孕线
      - morning_star: 晨星（底部反转）
      - evening_star: 暮星（顶部反转）
      - three_white: 三白兵（强势上涨）
      - three_black: 三黑鸦（强势下跌）

    Returns:
        DataFrame with boolean columns for each pattern
    """
    body = (close - open_).abs()
    total_range = high - low
    upper_shadow = high - close.where(close > open_, open_)
    lower_shadow = open_.where(close > open_, close) - low

    # 实体占比（避免除以0）
    body_pct = body / total_range.replace(0, np.nan)
    upper_pct = upper_shadow / total_range.replace(0, np.nan)
    lower_pct = lower_shadow / total_range.replace(0, np.nan)

    # 各种形态的判断条件
    patterns = pd.DataFrame(index=close.index)

    # 锤子线: 小实体在下部，下影线至少实体2倍，上影线短
    patterns["hammer"] = (
        (body_pct < 0.35) & (lower_pct > 0.55) & (upper_pct < 0.15)
    )

    # 射击之星: 小实体在上部，上影线至少实体2倍，下影线短
    patterns["shooting_star"] = (
        (body_pct < 0.35) & (upper_pct > 0.55) & (lower_pct < 0.15)
    )

    # 十字星: 极小的实体
    body_ratio = body / close.shift(1).abs().replace(0, np.nan)
    patterns["doji"] = body_ratio < 0.005

    # 阳包阴 / 阴包阳: 需要比较前后两根K线
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    prev_body = prev_close - prev_open
    prev_body_abs = prev_body.abs()

    # 阳包阴: 前一根阴线，后一根阳线，且阳实体完全覆盖阴实体
    patterns["engulfing_bull"] = (
        (prev_body < 0) &  # 前阴
        (close > open_) &  # 今阳
        (close > prev_open) &  # 收盘高于前开盘
        (open_ < prev_close)  # 开盘低于前收盘
    )

    # 阴包阳: 前一根阳线，后一根阴线，且阴实体完全覆盖阳实体
    patterns["engulfing_bear"] = (
        (prev_body > 0) &  # 前阳
        (close < open_) &  # 今阴
        (close < prev_open) &  # 收盘低于前开盘
        (open_ > prev_close)  # 开盘高于前收盘
    )

    # 晨星: 长阴→小实体（可十字）→长阳，阳线收盘超过阴线中点
    prev2_close = close.shift(2)
    prev2_open = open_.shift(2)
    prev2_body = prev2_close - prev2_open
    # 中间日（Day-1）的小实体判断应使用前一天的body
    prev_body = body.shift(1)
    prev_total_range = total_range.shift(1)
    patterns["morning_star"] = (
        (prev2_body < -0.02 * close.shift(2)) &  # 2日前长阴
        (prev_body < 0.5 * prev_total_range) &  # 昨日小实体
        (close - open_ > 0.02 * open_) &  # 今日长阳
        (close > (prev2_open + prev2_close) / 2)  # 超过阴线中点
    )

    # 暮星: 长阳→小实体→长阴，阴线收盘超过阳线中点
    patterns["evening_star"] = (
        (prev2_body > 0.02 * close.shift(2)) &  # 2日前长阳
        (prev_body < 0.5 * prev_total_range) &  # 昨日小实体
        (close - open_ < -0.02 * open_) &  # 今日长阴
        (close < (prev2_open + prev2_close) / 2)  # 超过阳线中点
    )

    # 三白兵: 连续3根阳线，每根收盘价创新高
    patterns["three_white"] = (
        (close > open_) &
        (close.shift(1) > open_.shift(1)) &
        (close.shift(2) > open_.shift(2)) &
        (close > close.shift(1)) &
        (close.shift(1) > close.shift(2))
    )

    # 三黑鸦: 连续3根阴线，每根收盘价创新低
    patterns["three_black"] = (
        (close < open_) &
        (close.shift(1) < open_.shift(1)) &
        (close.shift(2) < open_.shift(2)) &
        (close < close.shift(1)) &
        (close.shift(1) < close.shift(2))
    )

    # 看涨孕线: 大阴线后小阳线（实体在阴线实体内）
    patterns["harami_bull"] = (
        (prev_body < -0.02 * prev_close) &  # 前长阴
        (close > open_) &  # 今阳
        (body < prev_body_abs * 0.5) &  # 今实体小于前一半
        (open_ > prev_close) &  # 开盘在前收盘之上
        (close < prev_open)  # 收盘在前开盘之下
    )

    # 看跌孕线: 大阳线后小阴线（实体在阳线实体内）
    patterns["harami_bear"] = (
        (prev_body > 0.02 * prev_close) &  # 前长阳
        (close < open_) &  # 今阴
        (body < prev_body_abs * 0.5) &  # 今实体小于前一半
        (open_ < prev_close) &  # 开盘在前收盘之下
        (close > prev_open)  # 收盘在前开盘之上
    )

    return patterns


def compute_pattern_score(patterns: pd.DataFrame, latest: int = -1) -> float:
    """
    计算K线形态综合评分（-100到+100）

    正值=看涨，负值=看跌，绝对值越大信号越强。

    Args:
        patterns: detect_candlestick_patterns 的返回结果
        latest: 取最近N天的形态（默认仅取当天）

    Returns:
        形态评分
    """
    if patterns.empty:
        return 0

    recent = patterns.iloc[latest:] if latest < 0 else patterns.iloc[-latest:]
    if recent.empty:
        return 0

    # 各形态的权重
    weights = {
        "hammer": 25,
        "shooting_star": -25,
        "engulfing_bull": 35,
        "engulfing_bear": -35,
        "doji": -5,
        "harami_bull": 20,
        "harami_bear": -20,
        "morning_star": 40,
        "evening_star": -40,
        "three_white": 30,
        "three_black": -30,
    }

    score = 0.0
    for col, weight in weights.items():
        if col in recent.columns:
            count = recent[col].sum()
            score += count * weight

    # 归一化到 ±100
    return max(-100, min(100, score))


def compute_support_resistance(close: pd.Series, high: pd.Series,
                                low: pd.Series) -> Tuple[list, list]:
    """
    基于价格极值计算支撑位和阻力位

    算法：取最近60日的高低点作为关键价位区间，
    配合近期均线作为动态支撑阻力。

    Args:
        close: 收盘价
        high: 最高价
        low: 最低价

    Returns:
        (支撑位列表, 阻力位列表)，各取3个关键价位
    """
    if len(close) < 20:
        return [], []

    latest_close = close.iloc[-1]

    # 最近60日的高低点
    lookback = min(60, len(close))
    recent_high = high.iloc[-lookback:]
    recent_low = low.iloc[-lookback:]

    # 找局部极值点
    resistance = []
    support = []

    # 取近期高点中高于当前价的作为阻力位
    highs_above = sorted(recent_high[recent_high > latest_close].unique(), reverse=True)
    resistance = highs_above[:3]

    # 取近期低点中低于当前价的作为支撑位
    lows_below = sorted(recent_low[recent_low < latest_close].unique())
    support = lows_below[:3]

    return support, resistance
