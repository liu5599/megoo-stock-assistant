"""
指南针风格买卖点选股器
====================
设计理念（借鉴指南针+知乎用户反馈）：
  1. 三把锁体系：资金锁 + 趋势锁 + 信号锁 → 三重验证
  2. 先判大势，再选个股（由大到小、层层过滤）
  3. 输出明确B/S买卖点，而非抽象评分
  4. 多周期：T+1超短 / T+3短线 / 波段中线 / 价值长线

信号体系（总分100）：
  资金锁 30分 | 趋势锁 30分 | 信号锁 40分
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from utils.logger import logger


@dataclass
class TradeSignal:
    """买卖点信号"""
    code: str
    name: str
    price: float
    period: str                     # T+1 / T+3 / 波段 / 长线

    # 三把锁评分
    capital_score: float = 0        # 资金锁 0-30
    trend_score: float = 0          # 趋势锁 0-30
    signal_score: float = 0         # 信号锁 0-40
    total_score: float = 0          # 总分

    # 信号明细
    reasons: List[str] = field(default_factory=list)

    # 买卖点位（指南针风格）
    buy_price: float = 0            # 建议买入价 B
    stop_loss: float = 0            # 止损价
    target_1: float = 0             # 第一目标
    target_2: float = 0             # 第二目标

    # 操作建议
    action: str = ""                # BUY / WATCH / AVOID
    confidence: str = ""            # 高 / 中 / 低
    position_pct: float = 0         # 建议仓位%
    hold_days: str = ""             # 建议持有天数

    # 关键指标
    atr: float = 0
    ma20: float = 0
    vol_ratio: float = 1.0
    market_heat: float = 50         # 大盘热度


class CompassScreener:
    """
    指南针风格选股器
    ================
    三把锁体系：资金锁 + 趋势锁 + 信号锁
    """

    def __init__(self):
        self.market_heat = 50

    def set_market_heat(self, heat: float):
        """设置大盘热度（影响仓位建议）"""
        self.market_heat = heat

    # ═══════════════════════════════════════════════
    # 大势判断
    # ═══════════════════════════════════════════════

    def judge_market(self, sentiment) -> dict:
        """判断大盘强弱状态"""
        heat = getattr(sentiment, 'market_heat_index', 50)
        up = getattr(sentiment, 'advance_count', 0)
        down = getattr(sentiment, 'decline_count', 0)
        limit_up = getattr(sentiment, 'limit_up_count', 0)

        # 涨跌比
        if up + down > 0:
            ratio = up / (up + down)
        else:
            ratio = 0.5

        if heat >= 70 and ratio > 0.65 and limit_up > 80:
            status = "强势"
            position = 80
            action = "积极做多，满仓操作"
        elif heat >= 55 and ratio > 0.5:
            status = "偏强"
            position = 60
            action = "正常操作，精选个股"
        elif heat >= 40:
            status = "震荡"
            position = 40
            action = "控制仓位，快进快出"
        elif heat >= 25:
            status = "偏弱"
            position = 20
            action = "轻仓或观望，严格止损"
        else:
            status = "弱势"
            position = 10
            action = "建议空仓，等待信号"

        self.market_heat = heat
        return {
            "status": status, "heat": heat,
            "up_down_ratio": round(ratio * 100, 1),
            "limit_up": limit_up,
            "position_pct": position,
            "advice": action,
        }

    # ═══════════════════════════════════════════════
    # 三把锁评分
    # ═══════════════════════════════════════════════

    def _capital_lock(self, df: pd.DataFrame, period: str) -> Tuple[float, List[str]]:
        """
        资金锁（满分30）：量价关系反映资金进出
        - 放量上涨：主力资金进入
        - 量能持续放大：资金持续流入
        - 缩量下跌后放量反弹：洗盘结束
        """
        score = 0
        reasons = []
        if len(df) < 10:
            return 0, reasons

        close = df["close"]
        volume = df["volume"]

        # 1. 近5日放量上涨（主力资金进场）
        if len(close) >= 6:
            price_chg_5d = float((close.iloc[-1] / close.iloc[-5] - 1) * 100)
            vol_ratio_5d = float(volume.iloc[-5:].mean()) / float(volume.iloc[-10:-5].mean()) if len(volume) >= 10 else 1

            if vol_ratio_5d > 1.5 and price_chg_5d > 3:
                score += 15
                reasons.append(f"💰 主力资金进场：5日放量{vol_ratio_5d:.1f}倍，涨幅{price_chg_5d:.1f}%")
            elif vol_ratio_5d > 1.3 and price_chg_5d > 1:
                score += 10
                reasons.append(f"📈 资金温和流入：量比{vol_ratio_5d:.1f}")

        # 2. 近3日量能递增（持续流入）
        if len(volume) >= 4:
            v1, v2, v3 = float(volume.iloc[-1]), float(volume.iloc[-2]), float(volume.iloc[-3])
            if v1 > v2 > v3:
                score += 10
                reasons.append("📊 量能递增：资金持续流入3日")

        # 3. 缩量后放量反弹（洗盘结束信号）
        if len(volume) >= 15:
            prev_5d_vol = float(volume.iloc[-10:-5].mean())
            curr_5d_vol = float(volume.iloc[-5:].mean())
            prev_5d_price = float((close.iloc[-6] / close.iloc[-10] - 1) * 100) if len(close) >= 10 else 0
            curr_5d_price = price_chg_5d if len(close) >= 6 else 0
            if prev_5d_vol < volume.iloc[-15:-10].mean() * 0.7 and curr_5d_vol > prev_5d_vol * 1.3 and curr_5d_price > 0:
                score += 5
                reasons.append("🔄 洗盘结束：缩量后放量反弹")

        return min(score, 30), reasons

    def _trend_lock(self, df: pd.DataFrame, period: str) -> Tuple[float, List[str]]:
        """
        趋势锁（满分30）：均线排列+价格位置判断趋势
        """
        score = 0
        reasons = []
        if len(df) < 21:
            return 0, reasons

        close = df["close"]
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        latest = float(close.iloc[-1])
        ma5_v = float(ma5.iloc[-1])
        ma10_v = float(ma10.iloc[-1])
        ma20_v = float(ma20.iloc[-1])
        ma60_v = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else 0

        # 1. 多头排列检查
        if ma5_v > ma10_v > ma20_v:
            score += 12
            reasons.append("📊 均线多头排列 MA5>MA10>MA20")
        elif ma5_v > ma10_v:
            score += 6
            reasons.append("📈 短均金叉 MA5>MA10")

        # 2. 价格位置
        if latest > ma5_v > ma10_v:
            score += 8
            reasons.append("📍 价格站上所有短均线")
        elif latest > ma20_v:
            score += 4

        # 3. 价格上穿MA20（趋势转折信号）
        prev_c = float(close.iloc[-2]) if len(close) >= 2 else latest
        prev_ma20 = float(ma20.iloc[-2]) if not pd.isna(ma20.iloc[-2]) else ma20_v
        if prev_c <= prev_ma20 and latest > ma20_v:
            score += 10
            reasons.append("🔥 价格上穿MA20——趋势转多信号")

        return min(score, 30), reasons

    def _signal_lock(self, df: pd.DataFrame, period: str) -> Tuple[float, List[str]]:
        """
        信号锁（满分40）：MACD/KDJ/RSI/形态 多重技术信号共振
        """
        score = 0
        reasons = []
        if len(df) < 26:
            return 0, reasons

        from analysis.indicators import (
            compute_macd, compute_kdj, compute_rsi, compute_bollinger,
            detect_candlestick_patterns, compute_pattern_score,
        )

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # 1. MACD信号（0-12分）
        macd = compute_macd(close)
        if len(macd) >= 3:
            dif = float(macd["dif"].iloc[-1])
            dea = float(macd["dea"].iloc[-1])
            prev_dif = float(macd["dif"].iloc[-2])
            prev_dea = float(macd["dea"].iloc[-2])
            macd_bar = float(macd["macd"].iloc[-1])

            # 近3日金叉
            has_golden = False
            for i in range(-1, -4, -1):
                if abs(i) <= len(macd):
                    pdif = float(macd["dif"].iloc[i-1])
                    pdea = float(macd["dea"].iloc[i-1])
                    cdif = float(macd["dif"].iloc[i])
                    cdea = float(macd["dea"].iloc[i])
                    if pdif <= pdea and cdif > cdea:
                        has_golden = True
                        day = "今日" if i == -1 else "昨日" if i == -2 else "前日"
                        reasons.append(f"✨ MACD{day}金叉")
                        break

            if has_golden:
                score += 10
            elif dif > dea and macd_bar > 0:
                score += 5
                reasons.append("📈 MACD多头运行")

        # 2. KDJ信号（0-8分）
        kdj = compute_kdj(high, low, close)
        if len(kdj) >= 3:
            k = float(kdj["k"].iloc[-1])
            d = float(kdj["d"].iloc[-1])
            pk = float(kdj["k"].iloc[-2])
            pd = float(kdj["d"].iloc[-2])

            if pk <= pd and k > d and k < 50:
                score += 8
                reasons.append(f"✨ KDJ低位金叉(K={k:.0f}<50)")
            elif pk <= pd and k > d:
                score += 5
                reasons.append(f"📈 KDJ金叉(K={k:.0f})")
            elif k < 30:
                score += 3
                reasons.append(f"📉 KDJ超卖区(K={k:.0f})，有望反弹")

        # 3. RSI信号（0-8分）
        rsi = compute_rsi(close)
        rsi_v = float(rsi.iloc[-1])
        if 40 <= rsi_v <= 60:
            score += 5
        elif 30 <= rsi_v < 40:
            score += 8
            reasons.append(f"📉 RSI={rsi_v:.0f} 偏低位，上涨空间大")

        # 4. K线形态（0-8分）
        patterns = detect_candlestick_patterns(df["open"], high, low, close)
        p_score = compute_pattern_score(patterns)
        if p_score >= 25:
            latest_p = patterns.iloc[-3:]
            for col in ["hammer", "engulfing_bull", "morning_star", "three_white"]:
                if col in latest_p.columns and latest_p[col].any():
                    names = {
                        "hammer": "🔨 锤子线",
                        "engulfing_bull": "🔥 阳包阴",
                        "morning_star": "⭐ 晨星",
                        "three_white": "💪 三白兵",
                    }
                    reasons.append(f"{names.get(col, col)}——看涨形态")
            score += 8

        # 5. 布林带收窄突破（0-4分）
        boll = compute_bollinger(close)
        if len(boll) >= 6:
            bw_now = float(boll["bandwidth"].iloc[-1])
            bw_prev = float(boll["bandwidth"].iloc[-6:-1].mean())
            if bw_now > bw_prev * 1.1 and latest > float(boll["middle"].iloc[-1]):
                score += 4
                reasons.append("📊 布林带向上开口")

        return min(score, 40), reasons

    # ═══════════════════════════════════════════════
    # 买卖点位计算
    # ═══════════════════════════════════════════════

    def calc_trade_points(self, df: pd.DataFrame, price: float) -> dict:
        """计算买入价B、止损价、目标价"""
        close = df["close"]
        high = df["high"]
        low = df["low"]

        from analysis.indicators import compute_atr

        atr = compute_atr(high, low, close)
        atr_v = float(atr.iloc[-1]) if not atr.empty else price * 0.02

        # 止损价 = max(ATR×2, MA20, 近10日最低)
        ma20 = float(close.rolling(20).mean().iloc[-1])
        low_10 = float(low.iloc[-10:].min())
        stop = max(price - atr_v * 2, ma20, low_10)

        # 目标价1（保守）= 前20日高点
        high_20 = float(high.iloc[-20:].max())
        target_1 = max(high_20, price * 1.03)

        # 目标价2（激进）= 前高 + 风险×1.5
        risk = price - stop
        target_2 = high_20 + risk * 1.5 if risk > 0 else price * 1.1

        rr = (target_1 - price) / risk if risk > 0 else 0

        return {
            "buy": round(price, 2),
            "stop": round(stop, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "risk_reward": round(rr, 2),
            "atr": round(atr_v, 2),
            "ma20": round(ma20, 2),
            "stop_pct": round((price - stop) / price * 100, 2),
            "gain_pct": round((target_1 / price - 1) * 100, 2),
        }

    # ═══════════════════════════════════════════════
    # 单股综合评估
    # ═══════════════════════════════════════════════

    def evaluate(self, code: str, name: str, df: pd.DataFrame,
                 period: str = "T+3") -> Optional[TradeSignal]:
        """综合评估一只股票的三把锁+买卖点"""
        if df.empty or len(df) < 26:
            return None

        price = float(df["close"].iloc[-1])

        # 三把锁
        cap_s, cap_r = self._capital_lock(df, period)
        trend_s, trend_r = self._trend_lock(df, period)
        sig_s, sig_r = self._signal_lock(df, period)

        total = cap_s + trend_s + sig_s
        all_reasons = cap_r + trend_r + sig_r

        # 三把锁至少点亮两把
        locks_ok = sum([cap_s >= 15, trend_s >= 15, sig_s >= 15])
        if locks_ok < 2:
            return None

        # 买卖点
        pts = self.calc_trade_points(df, price)
        rr = pts["risk_reward"]

        # 筛选条件
        min_score = {"T+1": 55, "T+3": 50, "波段": 45, "长线": 40}.get(period, 45)
        min_rr = {"T+1": 2.0, "T+3": 1.5, "波段": 1.2, "长线": 1.0}.get(period, 1.2)

        if total < min_score or rr < min_rr:
            return None

        # 仓位建议（大盘热度影响）
        heat_factor = max(0.3, self.market_heat / 100)
        base_pos = {"T+1": 15, "T+3": 25, "波段": 40, "长线": 60}.get(period, 30)
        position = min(80, base_pos * heat_factor * 1.5)

        # 信心等级
        if total >= 75 and locks_ok >= 3:
            confidence = "高"
        elif total >= 60:
            confidence = "中"
        else:
            confidence = "低"

        hold_days = {"T+1": "1-2天", "T+3": "3-5天", "波段": "1-2周", "长线": "1-3月"}.get(period, "")

        return TradeSignal(
            code=code, name=name, price=price, period=period,
            capital_score=cap_s, trend_score=trend_s, signal_score=sig_s,
            total_score=round(total, 1),
            reasons=all_reasons,
            buy_price=pts["buy"], stop_loss=pts["stop"],
            target_1=pts["target_1"], target_2=pts["target_2"],
            action="BUY", confidence=confidence,
            position_pct=round(position, 1), hold_days=hold_days,
            atr=pts["atr"], ma20=pts["ma20"],
            vol_ratio=float(df["volume"].iloc[-5:].mean() / df["volume"].iloc[-10:-5].mean()) if len(df) >= 10 else 1,
            market_heat=self.market_heat,
        )

    # ═══════════════════════════════════════════════
    # 批量选股
    # ═══════════════════════════════════════════════

    def screen(self, kline_data: dict, stock_names: dict,
               period: str = "T+3", top_n: int = 20) -> List[TradeSignal]:
        """批量筛选"""
        results = []
        for code, df in kline_data.items():
            try:
                sig = self.evaluate(code, stock_names.get(code, code), df, period)
                if sig:
                    results.append(sig)
            except Exception as e:
                logger.debug(f"评估失败 {code}: {e}")

        results.sort(key=lambda x: x.total_score, reverse=True)
        return results[:top_n]

    # ═══════════════════════════════════════════════
    # 格式化输出（指南针风格）
    # ═══════════════════════════════════════════════

    def format_market(self, judge: dict) -> str:
        """大盘状态"""
        emoji = {"强势": "🟢", "偏强": "🟢", "震荡": "🟡", "偏弱": "🟠", "弱势": "🔴"}
        e = emoji.get(judge["status"], "⚪")
        return (
            f"\n{e} 大盘状态: {judge['status']} | 热度{judge['heat']:.0f} | "
            f"涨跌比{judge['up_down_ratio']}% | 涨停{judge['limit_up']}家\n"
            f"   仓位建议: {judge['position_pct']}% | {judge['advice']}"
        )

    def format_signal(self, s: TradeSignal) -> str:
        """指南针风格买卖点输出"""
        lock_emoji = lambda v: "🔒" if v >= 15 else "🔓"
        stars = "⭐" * min(5, int(s.total_score / 20) + 1)

        lines = [
            f"\n{'─'*60}",
            f"  {stars} {s.name}({s.code}) | 周期: {s.period} | 现价: {s.price:.2f}",
            f"  {'─'*60}",
            f"  🔐 三把锁状态:",
            f"     {lock_emoji(s.capital_score)} 资金锁 {s.capital_score}/30",
            f"     {lock_emoji(s.trend_score)} 趋势锁 {s.trend_score}/30",
            f"     {lock_emoji(s.signal_score)} 信号锁 {s.signal_score}/40",
        ]

        if s.reasons:
            lines.append(f"  📋 信号明细:")
            for r in s.reasons:
                lines.append(f"     {r}")

        lines += [
            f"  {'─'*60}",
            f"  🎯 买卖点位（指南针风格）:",
            f"     🟢 B 买入价: {s.buy_price:.2f}",
            f"     🔴 止损价:  {s.stop_loss:.2f} ({(s.buy_price-s.stop_loss)/s.buy_price*100:.1f}%)",
            f"     🎯 目标1:   {s.target_1:.2f} (+{(s.target_1/s.buy_price-1)*100:.1f}%)",
            f"     🚀 目标2:   {s.target_2:.2f} (+{(s.target_2/s.buy_price-1)*100:.1f}%)",
            f"  {'─'*60}",
            f"  📊 建议仓位: {s.position_pct:.0f}% | 持有: {s.hold_days} | 信心: {s.confidence}",
            f"  📈 ATR:{s.atr:.2f} | MA20:{s.ma20:.2f} | 量比:{s.vol_ratio:.1f}",
        ]
        return "\n".join(lines)

    def format_table(self, signals: List[TradeSignal], period: str = "") -> str:
        """排名表格"""
        period_str = f"（{period}）" if period else ""
        if not signals:
            return f"⚠️ 暂无符合条件的{period_str}信号"

        lines = [
            f"\n{'='*95}",
            f"  🔥 {'三把锁' if not period else period}选股结果{period_str}——资金+趋势+信号 三重验证",
            f"{'='*95}",
            f"  {'排名':<4} {'代码':<8} {'名称':<8} {'总分':<5} {'资金':<5} {'趋势':<5} {'信号':<5} {'买入B':<8} {'止损':<8} {'目标':<8} {'仓位':<5} {'周期':<6}",
            f"  {'-'*88}",
        ]

        for i, s in enumerate(signals, 1):
            if i > 20:
                break
            lines.append(
                f"  {i:<4} {s.code:<8} {s.name[:6]:<8} {s.total_score:<5.0f} "
                f"{s.capital_score:<5.0f} {s.trend_score:<5.0f} {s.signal_score:<5.0f} "
                f"{s.buy_price:<8.2f} {s.stop_loss:<8.2f} {s.target_1:<8.2f} "
                f"{s.position_pct:<5.0f}% {s.hold_days:<6}"
            )

        lines += [
            f"{'='*95}",
            f"  ⚠️ 信号仅供参考，不构成投资建议 | 严格执行止损 | 三把锁全亮胜率最高",
        ]
        return "\n".join(lines)
