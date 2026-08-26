"""
风险管理模块
==========
核心能力：止损、止盈、仓位管理、风险评估，做"割肉高手"。

功能：
  - 动态止损位计算（ATR止损、均线止损、固定比例止损、移动止损）
  - 止盈位计算（固定比例、阻力位、趋势突破）
  - 仓位管理（凯利公式、风险平价、最大回撤控制）
  - 整体投资组合风险评估
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import logger


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class StopLossType(Enum):
    """止损类型"""
    ATR = "atr"                  # ATR动态止损
    MA = "ma"                    # 均线止损
    FIXED_PCT = "fixed_pct"     # 固定比例止损
    TRAILING = "trailing"       # 移动止损
    SUPPORT = "support"         # 支撑位止损
    VOLATILITY = "volatility"   # 波动率止损


class TakeProfitType(Enum):
    """止盈类型"""
    FIXED_PCT = "fixed_pct"     # 固定比例止盈
    RESISTANCE = "resistance"   # 阻力位止盈
    TRAILING = "trailing"       # 移动止盈
    RISK_REWARD = "risk_reward" # 风险回报比止盈


@dataclass
class StopLossLevel:
    """止损位结果"""
    price: float                # 止损价格
    stop_type: StopLossType     # 止损类型
    distance_pct: float         # 距现价百分比
    confidence: float           # 置信度 0-100
    reason: str = ""            # 说明


@dataclass
class TakeProfitLevel:
    """止盈位结果"""
    price: float
    tp_type: TakeProfitType
    distance_pct: float
    confidence: float
    reason: str = ""


@dataclass
class PositionSizing:
    """仓位建议"""
    suggested_shares: int       # 建议买入股数
    suggested_amount: float     # 建议买入金额
    position_pct: float         # 占总资金百分比
    risk_per_share: float       # 单股风险金额
    total_risk_pct: float       # 总风险占比
    kelly_fraction: float       # 凯利公式建议仓位
    method: str = ""            # 计算方法


@dataclass
class RiskAssessment:
    """个股风险评估"""
    overall_risk_level: str        # low / medium / high / extreme
    overall_risk_score: float      # 0-100, 越高越危险
    stop_loss: Optional[StopLossLevel] = None
    take_profit: Optional[TakeProfitLevel] = None
    max_drawdown_pct: float = 0
    volatility_pct: float = 0
    beta: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    position_sizing: Optional[PositionSizing] = None


@dataclass
class SellSignal:
    """卖出信号"""
    signal_type: str            # cut_loss / take_profit / trend_reversal / stop_loss_hit / manual
    strength: float             # 0-100 信号强度
    reason: str                 # 卖出理由
    urgency: str                # immediate / today / this_week
    price_target: Optional[float] = None  # 目标卖出价


# ═══════════════════════════════════════════════════════════════
# 风险管理器
# ═══════════════════════════════════════════════════════════════

class RiskManager:
    """
    风险管理器
    =========
    输入K线数据和财务数据，输出止损位、止盈位、仓位建议和风险评估。
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: 风险配置参数
        """
        self.config = config or {}
        self._default_stop_loss_pct = self.config.get("default_stop_loss_pct", 0.07)   # 默认止损7%
        self._default_take_profit_pct = self.config.get("default_take_profit_pct", 0.15) # 默认止盈15%
        self._atr_multiplier = self.config.get("atr_multiplier", 2.0)   # ATR倍数止损
        self._trailing_activation_pct = self.config.get("trailing_activation_pct", 0.10) # 移动止损激活涨幅
        self._trailing_stop_pct = self.config.get("trailing_stop_pct", 0.08)  # 移动止损回撤幅度
        self._max_position_pct = self.config.get("max_position_pct", 0.20)  # 单只最大仓位
        self._risk_free_rate = self.config.get("risk_free_rate", 0.025)     # 无风险利率

    # ======================== 止损位计算 ========================

    def calc_atr_stop(
        self, close: pd.Series, high: pd.Series, low: pd.Series,
        current_price: float, atr_period: int = 14
    ) -> StopLossLevel:
        """ATR动态止损 — 适合波动大的股票"""
        from analysis.indicators import compute_atr
        atr_series = compute_atr(high, low, close, atr_period)
        atr_val = float(atr_series.iloc[-1]) if not atr_series.empty else current_price * 0.03
        stop_price = current_price - self._atr_multiplier * atr_val
        distance = (current_price - stop_price) / current_price
        confidence = min(85, 50 + 35 * (1 - abs(distance - 0.07) / 0.10))
        return StopLossLevel(
            price=round(stop_price, 2),
            stop_type=StopLossType.ATR,
            distance_pct=round(distance * 100, 2),
            confidence=round(confidence, 0),
            reason=f"ATR({atr_period})={atr_val:.2f} × {self._atr_multiplier:.1f}倍 = {stop_price:.2f}",
        )

    def calc_ma_stop(
        self, close: pd.Series, current_price: float, ma_period: int = 60
    ) -> StopLossLevel:
        """均线止损 — 趋势交易常用"""
        if len(close) < ma_period:
            return self.calc_fixed_stop(current_price)
        ma = close.rolling(ma_period).mean()
        ma_val = float(ma.iloc[-1]) if not pd.isna(ma.iloc[-1]) else current_price * 0.92
        stop_price = ma_val
        distance = (current_price - stop_price) / current_price
        confidence = 75 if distance > 0.03 else 55
        return StopLossLevel(
            price=round(stop_price, 2),
            stop_type=StopLossType.MA,
            distance_pct=round(distance * 100, 2),
            confidence=round(confidence, 0),
            reason=f"MA{ma_period}={ma_val:.2f}",
        )

    def calc_fixed_stop(self, current_price: float, pct: Optional[float] = None) -> StopLossLevel:
        """固定比例止损"""
        pct = pct or self._default_stop_loss_pct
        stop_price = current_price * (1 - pct)
        return StopLossLevel(
            price=round(stop_price, 2),
            stop_type=StopLossType.FIXED_PCT,
            distance_pct=round(pct * 100, 2),
            confidence=70,
            reason=f"固定止损{pct*100:.0f}%",
        )

    def calc_trailing_stop(
        self, close: pd.Series, current_price: float
    ) -> StopLossLevel:
        """移动止损 — 保护利润"""
        if len(close) < 20:
            return self.calc_fixed_stop(current_price)

        # 计算过去20日最高价
        peak = float(close.iloc[-20:].max())
        gain_pct = (current_price - close.iloc[-20]) / close.iloc[-20]

        if gain_pct > self._trailing_activation_pct:
            # 已盈利超过激活线 → 启用移动止损
            stop_price = peak * (1 - self._trailing_stop_pct)
            distance = (current_price - stop_price) / current_price
            confidence = 85
            return StopLossLevel(
                price=round(stop_price, 2),
                stop_type=StopLossType.TRAILING,
                distance_pct=round(distance * 100, 2),
                confidence=confidence,
                reason=f"移动止损: 20日高点{peak:.2f} × (1-{self._trailing_stop_pct*100:.0f}%) = {stop_price:.2f}",
            )
        else:
            return self.calc_atr_stop(
                close, close, close * 0.98, current_price
            )

    def calc_support_stop(
        self, close: pd.Series, high: pd.Series, low: pd.Series,
        current_price: float
    ) -> StopLossLevel:
        """支撑位止损"""
        from analysis.indicators import compute_support_resistance
        support, _ = compute_support_resistance(close, high, low)
        if support:
            stop_price = support[0]
            distance = (current_price - stop_price) / current_price
            if 0.01 <= distance <= 0.20:
                return StopLossLevel(
                    price=round(stop_price, 2),
                    stop_type=StopLossType.SUPPORT,
                    distance_pct=round(distance * 100, 2),
                    confidence=80,
                    reason=f"支撑位: {stop_price:.2f}",
                )
        return self.calc_atr_stop(close, high, low, current_price)

    def get_best_stop_loss(
        self, df: pd.DataFrame, current_price: float
    ) -> StopLossLevel:
        """
        综合多种止损方法，取最优结果

        评估各方法给出的止损位，选择距离适中且最合理的。
        """
        if df.empty or len(df) < 15:
            return self.calc_fixed_stop(current_price)

        close = df["close"]
        high = df["high"]
        low = df["low"]

        stops = [
            ("ATR", self.calc_atr_stop(close, high, low, current_price)),
            ("MA60", self.calc_ma_stop(close, current_price, 60)),
            ("MA20", self.calc_ma_stop(close, current_price, 20)),
            ("固定7%", self.calc_fixed_stop(current_price)),
            ("支撑位", self.calc_support_stop(close, high, low, current_price)),
        ]

        # 选距离在3%-15%之间、置信度最高的
        best = None
        best_score = -1
        for name, sl in stops:
            if 0.03 <= sl.distance_pct / 100 <= 0.18:
                score = sl.confidence
                # 偏好ATR和支撑位
                if sl.stop_type in (StopLossType.ATR, StopLossType.SUPPORT):
                    score += 10
                if score > best_score:
                    best_score = score
                    best = sl

        return best or self.calc_fixed_stop(current_price)

    # ======================== 止盈位计算 ========================

    def calc_take_profit(
        self, df: pd.DataFrame, current_price: float,
        stop_loss_price: float
    ) -> TakeProfitLevel:
        """计算止盈位（风险回报比2:1 + 阻力位参考）"""
        if df.empty or len(df) < 20:
            return self._fixed_tp(current_price, stop_loss_price)

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # 方法1: 风险回报比
        risk = current_price - stop_loss_price
        reward_2x = current_price + risk * 2
        reward_3x = current_price + risk * 3

        # 方法2: 阻力位
        from analysis.indicators import compute_support_resistance
        _, resistance = compute_support_resistance(close, high, low)

        # 方法3: 前高
        prev_high_20 = float(high.iloc[-20:].max()) if len(high) >= 20 else current_price
        prev_high_60 = float(high.iloc[-60:].max()) if len(high) >= 60 else current_price

        candidates = [
            ("风险回报2:1", reward_2x, 75),
            ("风险回报3:1", reward_3x, 60),
        ]
        if resistance:
            candidates.append((f"阻力位{resistance[0]:.0f}", resistance[0], 80))
        if prev_high_60 > current_price * 1.05:
            candidates.append(("60日高点", prev_high_60, 70))
        if prev_high_20 > current_price * 1.03:
            candidates.append(("20日高点", prev_high_20, 65))

        # 过滤掉太近或太远的
        valid = [(n, p, c) for n, p, c in candidates
                 if 0.03 <= (p - current_price) / current_price <= 0.50]

        if not valid:
            return self._fixed_tp(current_price, stop_loss_price)

        # 选最近且置信度最高的
        valid.sort(key=lambda x: (x[1], -x[2]))
        best_name, best_price, best_conf = valid[0]

        distance = (best_price - current_price) / current_price
        return TakeProfitLevel(
            price=round(best_price, 2),
            tp_type=TakeProfitType.RISK_REWARD,
            distance_pct=round(distance * 100, 2),
            confidence=round(best_conf, 0),
            reason=f"{best_name}: {best_price:.2f} (+{distance*100:.1f}%)",
        )

    def _fixed_tp(self, current_price: float, stop_loss_price: float) -> TakeProfitLevel:
        """固定比例止盈（回退方案）"""
        risk = current_price - stop_loss_price
        tp_price = current_price + risk * 2  # 风险回报比2:1
        distance = (tp_price - current_price) / current_price
        return TakeProfitLevel(
            price=round(tp_price, 2),
            tp_type=TakeProfitType.FIXED_PCT,
            distance_pct=round(distance * 100, 2),
            confidence=60,
            reason=f"固定风险回报比2:1 → {tp_price:.2f}",
        )

    # ======================== 仓位管理 ========================

    def calc_position_size(
        self, total_capital: float, current_price: float,
        stop_loss_price: float, win_rate: float = 0.45,
        risk_per_trade_pct: float = 0.02
    ) -> PositionSizing:
        """
        计算建议仓位

        凯利公式 + 风险平价双重控制。

        Args:
            total_capital: 总资金
            current_price: 当前股价
            stop_loss_price: 止损价
            win_rate: 预估胜率（默认45%）
            risk_per_trade_pct: 单笔最大风险（默认2%）

        Returns:
            PositionSizing: 仓位建议
        """
        risk_per_share = abs(current_price - stop_loss_price)
        if risk_per_share < 0.01:
            risk_per_share = current_price * self._default_stop_loss_pct

        # 凯利公式: f* = (p * b - q) / b
        # p=胜率, q=败率, b=盈亏比
        loss_per_share = risk_per_share
        tp = self._fixed_tp(current_price, stop_loss_price)
        gain_per_share = tp.price - current_price
        win_loss_ratio = gain_per_share / loss_per_share if loss_per_share > 0 else 2.0
        kelly_f = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        kelly_f = max(0.01, min(kelly_f, self._max_position_pct))  # 限制最大仓位

        # 风险平价
        max_risk_amount = total_capital * risk_per_trade_pct
        shares_by_risk = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 0

        # 凯利建议
        kelly_amount = total_capital * kelly_f * 0.5  # 半凯利（更保守）
        shares_by_kelly = int(kelly_amount / current_price) if current_price > 0 else 0

        # 取两者较小值
        shares = min(shares_by_risk, shares_by_kelly)
        shares = max(shares, 100)  # 至少1手（A股）
        # 调整到100的整数倍（A股以手为单位）
        shares = (shares // 100) * 100
        if shares < 100:
            shares = 100

        amount = shares * current_price
        position_pct = amount / total_capital if total_capital > 0 else 0

        return PositionSizing(
            suggested_shares=shares,
            suggested_amount=round(amount, 2),
            position_pct=round(position_pct * 100, 2),
            risk_per_share=round(risk_per_share, 2),
            total_risk_pct=round(risk_per_trade_pct * 100, 2),
            kelly_fraction=round(kelly_f * 100, 1),
            method=f"半凯利({kelly_f*50:.1f}%) + 风险平价({risk_per_trade_pct*100:.0f}%)",
        )

    # ======================== 风险评估 ========================

    def assess_stock(
        self, df: pd.DataFrame, financial_data: Optional[Dict] = None,
        current_price: Optional[float] = None, total_capital: float = 100000
    ) -> RiskAssessment:
        """个股全面风险评估"""
        if df.empty or len(df) < 20:
            return RiskAssessment(overall_risk_level="high", overall_risk_score=70,
                                  warnings=["数据不足，无法准确评估"])

        close = df["close"]
        high = df["high"]
        low = df["low"]
        price = current_price or float(close.iloc[-1])

        # 计算关键风险指标
        from analysis.indicators import (
            compute_volatility, compute_max_drawdown, compute_atr
        )

        vol = float(compute_volatility(close).iloc[-1]) if len(close) >= 20 else 30
        max_dd, curr_dd, _ = compute_max_drawdown(close)
        atr_val = float(compute_atr(high, low, close).iloc[-1]) if len(close) >= 14 else price * 0.03

        # 波动率评分 (0-100)
        if vol < 20:
            vol_score = 20  # 低波动
        elif vol < 35:
            vol_score = 40
        elif vol < 50:
            vol_score = 60
        else:
            vol_score = 80

        # 回撤评分
        dd_val = abs(max_dd)
        if dd_val < 15:
            dd_score = 20
        elif dd_val < 30:
            dd_score = 50
        else:
            dd_score = 80

        # 流动性评分（ATR/价格）
        atr_pct = atr_val / price * 100
        if atr_pct > 5:
            liquidity_score = 70  # 波动大
        elif atr_pct > 3:
            liquidity_score = 50
        else:
            liquidity_score = 30

        # 综合风险评分
        risk_score = vol_score * 0.35 + dd_score * 0.35 + liquidity_score * 0.30
        risk_score = min(100, max(0, risk_score))

        if risk_score < 30:
            risk_level = "low"
        elif risk_score < 55:
            risk_level = "medium"
        elif risk_score < 75:
            risk_level = "high"
        else:
            risk_level = "extreme"

        # 止损位
        stop_loss = self.get_best_stop_loss(df, price)
        # 止盈位
        take_profit = self.calc_take_profit(df, price, stop_loss.price)
        # 仓位
        position = self.calc_position_size(total_capital, price, stop_loss.price)

        warnings = []
        if vol > 50:
            warnings.append(f"波动率过高({vol:.0f}%)，注意风险")
        if dd_val > 30:
            warnings.append(f"历史最大回撤{dd_val:.1f}%，需严格止损")
        if atr_pct > 5:
            warnings.append(f"单日振幅可达{atr_pct:.1f}%，不适合保守投资者")

        return RiskAssessment(
            overall_risk_level=risk_level,
            overall_risk_score=round(risk_score, 1),
            stop_loss=stop_loss,
            take_profit=take_profit,
            max_drawdown_pct=round(dd_val, 2),
            volatility_pct=round(vol, 2),
            position_sizing=position,
            warnings=warnings,
        )

    # ======================== 卖出信号检测 ========================

    def detect_sell_signals(
        self, df: pd.DataFrame, current_price: Optional[float] = None,
        cost_price: Optional[float] = None
    ) -> List[SellSignal]:
        """
        检测卖出信号

        综合判断是否需要"割肉"或止盈。

        Args:
            df: K线数据
            current_price: 当前价格
            cost_price: 成本价（如有持仓）

        Returns:
            卖出信号列表，按紧急程度排序
        """
        if df.empty:
            return []

        close = df["close"]
        high = df["high"]
        low = df["low"]
        price = current_price or float(close.iloc[-1])
        signals = []

        # 1. 止损信号（价格跌破止损位）
        stop_loss = self.get_best_stop_loss(df, price)
        if price <= stop_loss.price * 1.01:
            signals.append(SellSignal(
                signal_type="stop_loss_hit",
                strength=95,
                reason=f"价格{price:.2f}已触及止损位{stop_loss.price:.2f}，建议立即卖出",
                urgency="immediate",
                price_target=price,
            ))

        # 2. 趋势反转信号
        if len(close) >= 10:
            ma5 = float(close.rolling(5).mean().iloc[-1])
            ma10 = float(close.rolling(10).mean().iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])

            if ma5 < ma10 < ma20 and price < ma5:
                signals.append(SellSignal(
                    signal_type="trend_reversal",
                    strength=80,
                    reason=f"短期均线已空头排列(MA5={ma5:.2f}<MA10={ma10:.2f}<MA20={ma20:.2f})，趋势转弱",
                    urgency="today",
                ))

        # 3. 放量下跌信号
        if len(close) >= 5:
            vol = df["volume"]
            vol_ratio = float(vol.iloc[-1] / vol.iloc[-5:-1].mean()) if vol.iloc[-5:-1].mean() > 0 else 0
            price_change = (price / float(close.iloc[-2]) - 1) * 100
            if vol_ratio > 2.0 and price_change < -3:
                signals.append(SellSignal(
                    signal_type="cut_loss",
                    strength=85,
                    reason=f"放量下跌: 成交量{vol_ratio:.1f}倍，跌幅{price_change:.1f}%，资金出逃明显",
                    urgency="immediate",
                ))

        # 4. 如果有成本价，计算是否该止盈/止损
        if cost_price and cost_price > 0:
            gain_pct = (price - cost_price) / cost_price * 100
            if gain_pct > 20:
                # 盈利超过20%，检查是否该止盈
                if gain_pct > 50 or (gain_pct > 20 and price < float(close.iloc[-5:-1].max())):
                    signals.append(SellSignal(
                        signal_type="take_profit",
                        strength=70,
                        reason=f"盈利{gain_pct:.1f}%，已超过目标，建议分批止盈",
                        urgency="this_week",
                        price_target=price,
                    ))
            elif gain_pct < -self._default_stop_loss_pct * 100:
                signals.append(SellSignal(
                    signal_type="cut_loss",
                    strength=90,
                    reason=f"亏损{gain_pct:.1f}%已超止损线{self._default_stop_loss_pct*100:.0f}%，执行止损",
                    urgency="immediate",
                ))

        # 5. MACD死叉信号
        if len(close) >= 26:
            from analysis.indicators import compute_macd
            macd = compute_macd(close)
            if len(macd) >= 2:
                prev_dif = float(macd["dif"].iloc[-2])
                prev_dea = float(macd["dea"].iloc[-2])
                curr_dif = float(macd["dif"].iloc[-1])
                curr_dea = float(macd["dea"].iloc[-1])
                if prev_dif >= prev_dea and curr_dif < curr_dea:
                    signals.append(SellSignal(
                        signal_type="trend_reversal",
                        strength=75,
                        reason="MACD死叉出现，短期转空",
                        urgency="today",
                    ))

        # 按紧急程度排序
        urgency_order = {"immediate": 0, "today": 1, "this_week": 2}
        signals.sort(key=lambda s: urgency_order.get(s.urgency, 9))

        return signals
