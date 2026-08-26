"""
选股评级引擎
===========
集选股高手与割肉高手于一身，输出：
  - 综合买入评分（技术+基本面+情绪+资金+K线形态）
  - 行业相对强弱对比
  - 卖出信号与止损建议
  - 仓位管理建议
  - 完整选股报告
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

from analysis.technical import TechnicalAnalyzer
from factor_technical import (
    Momentum20Factor, Volatility20Factor, VolumePriceCorrFactor,
    RSIFactor, MADeviationFactor,
)
from factor_fundamental import (
    PEFactor, PBFactor, ROEFactor,
    RevenueGrowthFactor, ProfitGrowthFactor,
    DebtRatioFactor, GrossMarginFactor,
)
from factor_combiner import FactorCombiner
from engine.risk_manager import RiskManager, RiskAssessment, SellSignal
from utils.logger import logger


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class BuyScore:
    """买入评分"""
    total: float                # 综合得分 0-100
    technical: float            # 技术面 0-100
    fundamental: float          # 基本面 0-100
    risk_adjusted: float        # 风险调整后 0-100
    rating: str                 # 强烈推荐 / 推荐 / 观望 / 回避
    confidence: str             # 高 / 中 / 低


@dataclass
class StockAnalysisReport:
    """单只股票完整分析报告"""
    code: str
    name: str
    price: float
    sector: str = ""
    # 评分
    buy_score: Optional[BuyScore] = None
    # 技术分析
    technical_summary: Optional[Dict] = None
    # 基本面
    fundamental_summary: Optional[Dict] = None
    # 风险
    risk: Optional[RiskAssessment] = None
    # 卖出信号
    sell_signals: List[SellSignal] = field(default_factory=list)
    # 综合建议
    recommendation: str = ""       # buy / hold / sell / watch
    action_summary: str = ""      # 一句话建议
    generated_at: str = ""


# ═══════════════════════════════════════════════════════════════
# 选股评级引擎
# ═══════════════════════════════════════════════════════════════

class StockSelector:
    """
    选股评级引擎
    ===========
    集选股与割肉于一体，对单只股票或整个股票池进行全方位评级。
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.risk_manager = RiskManager(config.get("risk", {}))
        self._combiner_cache = {}

    # ======================== 多因子评分 ========================

    def _build_combiner(self) -> FactorCombiner:
        """构建多因子合成器（带缓存）"""
        config = {
            "strategy": {
                "technical_weight": self.config.get("tech_weight", 0.40),
                "fundamental_weight": self.config.get("fund_weight", 0.60),
                "top_n": 50,
                "normalization": "rank",
                "outlier_method": "winsorize",
                "outlier_percentile": 0.01,
            }
        }
        combiner = FactorCombiner(config)

        tech_factors = [
            Momentum20Factor(weight=0.20),
            Volatility20Factor(weight=0.15),
            VolumePriceCorrFactor(weight=0.15),
            RSIFactor(weight=0.25),
            MADeviationFactor(weight=0.25),
        ]
        fund_factors = [
            PEFactor(weight=0.20),
            PBFactor(weight=0.10),
            ROEFactor(weight=0.25),
            RevenueGrowthFactor(weight=0.15),
            ProfitGrowthFactor(weight=0.10),
            DebtRatioFactor(weight=0.10),
            GrossMarginFactor(weight=0.10),
        ]
        combiner.set_factors(tech_factors, fund_factors)
        return combiner

    def score_stock_multi_factor(
        self, df: pd.DataFrame, financial_data: Optional[Dict] = None
    ) -> Tuple[float, float, float]:
        """
        多因子评分

        Args:
            df: K线DataFrame
            financial_data: 财务数据字典

        Returns:
            (技术分, 基本面分, 总分) 0-100
        """
        if df.empty:
            return 50, 50, 50

        # 构建模拟多因子输入
        kline_data = {}
        fin_data = {}

        # 用当前数据模拟评分
        combiner = self._build_combiner()

        # 对单只股票计算因子值
        tech_score = 50
        fund_score = 50

        # 技术面综合评分
        if len(df) >= 20:
            try:
                from data.models import KLineData
                kline = KLineData(code="", df=df)
                analyzer = TechnicalAnalyzer(kline)
                # 手动调各信号方法
                from analysis.indicators import (
                    compute_rsi, compute_macd, compute_bollinger,
                    compute_volume_ratio, compute_price_momentum,
                )
                close = df["close"]
                high = df["high"]
                low = df["low"]
                volume = df["volume"]

                latest = float(close.iloc[-1])

                # RSI
                rsi = float(compute_rsi(close).iloc[-1]) if len(close) >= 14 else 50

                # 均线状态
                ma_short = float(close.rolling(5).mean().iloc[-1])
                ma_med = float(close.rolling(20).mean().iloc[-1])
                ma_long = float(close.rolling(60).mean().iloc[-1])

                # 动量
                mom_20 = float(compute_price_momentum(close, 20).iloc[-1]) if len(close) >= 21 else 0
                mom_60 = float(compute_price_momentum(close, 60).iloc[-1]) if len(close) >= 61 else 0

                # MACD
                macd = compute_macd(close) if len(close) >= 26 else None
                macd_signal = "neutral"
                if macd is not None and len(macd) >= 2:
                    dif = float(macd["dif"].iloc[-1])
                    dea = float(macd["dea"].iloc[-1])
                    prev_dif = float(macd["dif"].iloc[-2])
                    prev_dea = float(macd["dea"].iloc[-2])
                    if prev_dif <= prev_dea and dif > dea:
                        macd_signal = "golden_cross"
                    elif prev_dif >= prev_dea and dif < dea:
                        macd_signal = "death_cross"
                    elif dif > dea:
                        macd_signal = "bullish"
                    else:
                        macd_signal = "bearish"

                # 成交量
                vol_ratio = float(compute_volume_ratio(volume).iloc[-1]) if len(volume) >= 6 else 1.0
                price_change_5d = ((latest / float(close.iloc[-5]) - 1) * 100) if len(close) >= 5 else 0

                # ===== 技术评分 =====
                s_trend = 50
                if ma_short > ma_med > ma_long:
                    s_trend = 80
                elif ma_short < ma_med < ma_long:
                    s_trend = 20
                elif ma_short > ma_med:
                    s_trend = 60
                else:
                    s_trend = 40

                s_momentum = 50
                if mom_20 > 5 and mom_60 > 10:
                    s_momentum = 80
                elif mom_20 < -5 and mom_60 < -10:
                    s_momentum = 20
                elif mom_20 > 0:
                    s_momentum = 60
                else:
                    s_momentum = 35

                s_macd = {"golden_cross": 85, "bullish": 70,
                          "neutral": 50, "bearish": 30, "death_cross": 15}.get(macd_signal, 50)

                s_rsi = 50
                if 40 <= rsi <= 60:
                    s_rsi = 75
                elif rsi < 30:
                    s_rsi = 45  # 超卖可能反弹
                elif rsi > 70:
                    s_rsi = 25  # 超买
                elif rsi < 40:
                    s_rsi = 55
                else:
                    s_rsi = 40

                s_volume = 50
                if vol_ratio > 1.3 and price_change_5d > 3:
                    s_volume = 85  # 放量上涨
                elif vol_ratio > 1.3 and price_change_5d < -3:
                    s_volume = 15  # 放量下跌
                elif vol_ratio < 0.7 and price_change_5d < -3:
                    s_volume = 60  # 缩量下跌可能止跌
                elif vol_ratio < 0.7:
                    s_volume = 40  # 缩量

                # ===== K线形态评分 =====
                s_pattern = 50
                try:
                    from analysis.indicators import (
                        detect_candlestick_patterns, compute_pattern_score,
                    )
                    patterns = detect_candlestick_patterns(
                        df["open"], high, low, close
                    )
                    pattern_score = compute_pattern_score(patterns, latest=-5)
                    # pattern_score是-100~+100，映射到0~100
                    s_pattern = 50 + pattern_score * 0.40
                    s_pattern = max(30, min(85, s_pattern))
                except Exception:
                    pass

                tech_score = (
                    s_trend * 0.20 + s_momentum * 0.15 +
                    s_macd * 0.15 + s_rsi * 0.15 + s_volume * 0.10 +
                    s_pattern * 0.25  # K线形态占25%
                )
                tech_score = max(5, min(95, tech_score))

            except Exception as e:
                logger.debug(f"技术评分计算失败: {e}")
                tech_score = 50

        # 基本面评分
        if financial_data:
            try:
                pe = financial_data.get("pe")
                pb = financial_data.get("pb")
                roe = financial_data.get("roe")
                rev_g = financial_data.get("revenue_growth")
                profit_g = financial_data.get("profit_growth")
                debt = financial_data.get("debt_ratio")
                gross = financial_data.get("gross_margin")

                s_pe = 50
                if pe and pe > 0:
                    if pe < 15:
                        s_pe = 85
                    elif pe < 30:
                        s_pe = 65
                    elif pe < 50:
                        s_pe = 40
                    else:
                        s_pe = 20
                elif pe is not None and pe < 0:
                    s_pe = 30  # 亏损

                s_roe = 50
                if roe is not None:
                    if roe > 20:
                        s_roe = 90
                    elif roe > 15:
                        s_roe = 75
                    elif roe > 10:
                        s_roe = 60
                    elif roe > 5:
                        s_roe = 45
                    else:
                        s_roe = 25

                s_growth = 50
                if rev_g is not None:
                    if rev_g > 30:
                        s_growth = 85
                    elif rev_g > 15:
                        s_growth = 70
                    elif rev_g > 0:
                        s_growth = 55
                    else:
                        s_growth = 30

                s_debt = 50
                if debt is not None:
                    if debt < 30:
                        s_debt = 85
                    elif debt < 50:
                        s_debt = 65
                    elif debt < 70:
                        s_debt = 40
                    else:
                        s_debt = 20

                s_gross = 50
                if gross is not None:
                    if gross > 50:
                        s_gross = 80
                    elif gross > 30:
                        s_gross = 65
                    elif gross > 15:
                        s_gross = 45
                    else:
                        s_gross = 25

                fund_score = (
                    s_pe * 0.20 + s_roe * 0.25 + s_growth * 0.20 +
                    s_debt * 0.15 + s_gross * 0.20
                )
                fund_score = max(5, min(95, fund_score))

            except Exception as e:
                logger.debug(f"基本面评分计算失败: {e}")
                fund_score = 50

        # 加权总分
        tech_w = self.config.get("tech_weight", 0.40)
        fund_w = self.config.get("fund_weight", 0.60)
        total_score = tech_score * tech_w + fund_score * fund_w

        return round(tech_score, 1), round(fund_score, 1), round(total_score, 1)

    # ======================== 单只股票全息分析 ========================

    def analyze_stock(
        self,
        code: str,
        name: str,
        df: pd.DataFrame,
        financial_data: Optional[Dict] = None,
        cost_price: Optional[float] = None,
        total_capital: float = 100000,
    ) -> StockAnalysisReport:
        """
        全息分析一只股票

        Args:
            code: 股票代码
            name: 股票名称
            df: K线DataFrame
            financial_data: 财务数据
            cost_price: 成本价（如有持仓）
            total_capital: 总资金

        Returns:
            StockAnalysisReport: 完整分析报告
        """
        price = float(df["close"].iloc[-1]) if not df.empty else 0
        report = StockAnalysisReport(code=code, name=name, price=price)

        # 1. 多因子评分
        tech_s, fund_s, total_s = self.score_stock_multi_factor(df, financial_data)

        # 2. 风险评估与止损
        risk = self.risk_manager.assess_stock(df, financial_data, price, total_capital)
        report.risk = risk

        # 3. 风险调整后得分
        risk_penalty = risk.overall_risk_score / 100  # 0-1
        risk_adjusted = total_s * (1 - risk_penalty * 0.3)  # 最多惩罚30%

        # 4. 买入评级
        if risk_adjusted >= 75 and risk.overall_risk_level in ("low", "medium"):
            rating = "强烈推荐"
            confidence = "高"
            recommendation = "buy"
        elif risk_adjusted >= 60 and risk.overall_risk_level != "extreme":
            rating = "推荐"
            confidence = "中"
            recommendation = "buy"
        elif risk_adjusted >= 45:
            rating = "观望"
            confidence = "中"
            recommendation = "hold"
        elif risk_adjusted >= 30:
            rating = "谨慎"
            confidence = "低"
            recommendation = "watch"
        else:
            rating = "回避"
            confidence = "低"
            recommendation = "sell"

        report.buy_score = BuyScore(
            total=round(total_s, 1),
            technical=round(tech_s, 1),
            fundamental=round(fund_s, 1),
            risk_adjusted=round(risk_adjusted, 1),
            rating=rating,
            confidence=confidence,
        )

        # 5. 卖出信号（如果有持仓）
        report.sell_signals = self.risk_manager.detect_sell_signals(
            df, price, cost_price
        )

        # 6. 综合建议
        if recommendation == "buy":
            if risk.stop_loss:
                action = (
                    f"{rating}（评分{total_s:.0f}/风险调整{risk_adjusted:.0f}）"
                    f" | 止损{risk.stop_loss.price:.2f}"
                    f"({risk.stop_loss.distance_pct:.1f}%)"
                )
                if risk.take_profit:
                    action += f" | 止盈{risk.take_profit.price:.2f}(+{risk.take_profit.distance_pct:.1f}%)"
                if risk.position_sizing:
                    action += f" | 建议仓位{risk.position_sizing.position_pct:.1f}%"
        elif recommendation == "sell" or report.sell_signals:
            signals = [s for s in report.sell_signals if s.urgency == "immediate"]
            if signals:
                action = f"⚠️ 强烈卖出信号: {signals[0].reason}"
            else:
                action = f"评分较低({total_s:.0f})，建议观望或减仓"
        else:
            action = f"{rating}（评分{total_s:.0f}），等待更好机会"

        report.recommendation = recommendation
        report.action_summary = action

        # 7. 技术面摘要
        if len(df) >= 20:
            try:
                from data.models import KLineData
                kline = KLineData(code=code, df=df)
                ta = TechnicalAnalyzer(kline, config=default_config)
                ta.compute_all_indicators()

                trend = ta.get_trend_signal()
                macd_sig = ta.get_macd_signal()
                rsi_sig = ta.get_rsi_signal()
                kdj_sig = ta.get_kdj_signal()
                boll_sig = ta.get_bollinger_signal()
                vol_sig = ta.get_volume_signal()
                report.technical_summary = {
                    "trend": trend,
                    "macd": macd_sig,
                    "rsi": rsi_sig,
                    "kdj": kdj_sig,
                    "bollinger": boll_sig,
                    "volume": vol_sig,
                }
                # 补充K线形态分析
                try:
                    from analysis.indicators import (
                        detect_candlestick_patterns, compute_pattern_score,
                    )
                    patterns_df = detect_candlestick_patterns(
                        df["open"], df["high"], df["low"], df["close"]
                    )
                    pattern_score = compute_pattern_score(patterns_df)
                    # 找到最近出现的形态
                    latest = patterns_df.iloc[-3:].copy()
                    active = []
                    for col in latest.columns:
                        if latest[col].any():
                            count = int(latest[col].sum())
                            active.append(f"{col}({count}d)")
                    report.technical_summary["candlestick"] = {
                        "pattern_score": round(pattern_score, 0),
                        "recent_patterns": " + ".join(active[:5]) if active else "无",
                    }
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"技术分析失败: {e}")

        # 8. 基本面摘要
        if financial_data:
            report.fundamental_summary = {
                k: financial_data.get(k) for k in
                ["pe", "pb", "roe", "revenue_growth", "profit_growth",
                 "debt_ratio", "gross_margin", "dividend_yield"]
            }

        report.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        return report

    # ======================== 股票池批量评分 ========================

    def rank_stock_pool(
        self,
        kline_data: Dict[str, pd.DataFrame],
        financial_data: Dict[str, Dict],
        stock_names: Dict[str, str],
        top_n: int = 20,
    ) -> pd.DataFrame:
        """
        对股票池批量评分排名

        Args:
            kline_data: {code: df} K线数据
            financial_data: {code: {metrics}} 财务数据
            stock_names: {code: name} 名称映射
            top_n: 返回前N只

        Returns:
            DataFrame: 排名结果，含评分、风险、止损位等
        """
        rows = []
        for code, df in kline_data.items():
            if df.empty:
                continue
            fin = financial_data.get(code, {})
            name = stock_names.get(code, code)
            price = float(df["close"].iloc[-1])

            try:
                # 快速评分
                tech_s, fund_s, total_s = self.score_stock_multi_factor(df, fin)
                # 风险评估
                risk = self.risk_manager.assess_stock(df, fin, price)
                # 风险调整
                risk_penalty = risk.overall_risk_score / 100
                risk_adj = total_s * (1 - risk_penalty * 0.3)

                rows.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "tech_score": tech_s,
                    "fund_score": fund_s,
                    "total_score": total_s,
                    "risk_adjusted_score": round(risk_adj, 1),
                    "risk_level": risk.overall_risk_level,
                    "risk_score": risk.overall_risk_score,
                    "stop_loss": risk.stop_loss.price if risk.stop_loss else 0,
                    "stop_loss_pct": risk.stop_loss.distance_pct if risk.stop_loss else 0,
                    "take_profit": risk.take_profit.price if risk.take_profit else 0,
                    "take_profit_pct": risk.take_profit.distance_pct if risk.take_profit else 0,
                    "max_drawdown": risk.max_drawdown_pct,
                    "volatility": risk.volatility_pct,
                    "position_pct": risk.position_sizing.position_pct if risk.position_sizing else 0,
                })
            except Exception as e:
                logger.debug(f"评分失败 {code}: {e}")

        if not rows:
            return pd.DataFrame()

        result = pd.DataFrame(rows)

        # 按风险调整后得分排序
        result = result.sort_values("risk_adjusted_score", ascending=False)
        result["rank"] = range(1, len(result) + 1)

        # 重新排序列
        cols = ["rank", "code", "name", "price", "total_score",
                "risk_adjusted_score", "tech_score", "fund_score",
                "risk_level", "risk_score", "stop_loss", "stop_loss_pct",
                "take_profit", "take_profit_pct", "max_drawdown",
                "volatility", "position_pct"]
        result = result[[c for c in cols if c in result.columns]]

        return result.head(top_n)

    # ======================== 格式化输出 ========================

    def format_report(self, report: StockAnalysisReport) -> str:
        """格式化分析报告为可打印文本"""
        lines = []
        lines.append(f"{'='*70}")
        lines.append(f"  📊 {report.name} ({report.code}) — {report.price:.2f}")
        lines.append(f"{'='*70}")
        lines.append(f"  生成时间: {report.generated_at}")
        lines.append("")

        # 综合评级
        if report.buy_score:
            bs = report.buy_score
            stars = "⭐" * int(bs.total / 20) + "☆" * (5 - int(bs.total / 20))
            lines.append(f"  🎯 综合评级: {bs.rating} | 评分: {bs.total:.0f}/100")
            lines.append(f"     {stars}  (技术{bs.technical:.0f} + 基本面{bs.fundamental:.0f})")
            lines.append(f"     风险调整后: {bs.risk_adjusted:.0f}/100 | 置信度: {bs.confidence}")
            lines.append("")

        # 建议
        lines.append(f"  💡 操作建议: {report.action_summary}")
        lines.append("")

        # 止损止盈
        if report.risk:
            r = report.risk
            lines.append(f"  🛡️ 风险管理:")
            sl = r.stop_loss
            tp = r.take_profit
            if sl:
                lines.append(f"     - 止损位: {sl.price:.2f} ({sl.distance_pct:+.1f}%) [{sl.reason}]")
            if tp:
                lines.append(f"     - 止盈位: {tp.price:.2f} ({tp.distance_pct:+.1f}%) [{tp.reason}]")
            lines.append(f"     - 风险等级: {r.overall_risk_level.upper()} (评分{r.overall_risk_score:.0f}/100)")
            lines.append(f"     - 波动率: {r.volatility_pct:.1f}% | 最大回撤: {r.max_drawdown_pct:.1f}%")
            if r.position_sizing:
                ps = r.position_sizing
                lines.append(f"     - 建议仓位: {ps.position_pct:.1f}% ≈ {ps.suggested_shares}股/{ps.suggested_amount:.0f}元")
            for w in r.warnings:
                lines.append(f"     ⚠️ {w}")
            lines.append("")

        # 卖出信号
        if report.sell_signals:
            lines.append(f"  🔴 卖出信号:")
            for s in report.sell_signals:
                urgency_emoji = {"immediate": "🚨", "today": "⚠️", "this_week": "📅"}
                lines.append(f"     {urgency_emoji.get(s.urgency, '•')} [{s.urgency}] {s.reason}")
            lines.append("")

        # 技术面
        if report.technical_summary:
            t = report.technical_summary
            lines.append(f"  📈 技术分析:")
            if "trend" in t:
                d = t["trend"].get("direction", "?")
                d_emoji = {"bull": "🟢", "bear": "🔴", "sideways": "🟡"}
                lines.append(f"     均线趋势: {d_emoji.get(d, '⚪')} {d} | MA多头{t['trend'].get('ma_bull_count',0)}/空头{t['trend'].get('ma_bear_count',0)}")
            if "macd" in t:
                m = t["macd"]
                lines.append(f"     MACD: {m.get('signal','?')} (DIF={m.get('dif',0):.3f}, DEA={m.get('dea',0):.3f})")
            if "rsi" in t:
                r = t["rsi"]
                lines.append(f"     RSI({r.get('value',50):.1f}): {r.get('signal','?')}")
            if "volume" in t:
                v = t["volume"]
                lines.append(f"     量价: {v.get('signal','?')} | 量比{v.get('volume_ratio',1):.1f} | 5日涨跌{v.get('price_change_5d',0):.1f}%")
            if "candlestick" in t:
                c = t["candlestick"]
                lines.append(f"     K线形态: {c.get('recent_patterns','无')} | 评分{c.get('pattern_score',0):+.0f}")
            lines.append("")

        # 基本面
        if report.fundamental_summary:
            f = report.fundamental_summary
            lines.append(f"  💰 基本面:")
            if f.get("pe") is not None:
                lines.append(f"     PE: {f['pe']:.1f} | PB: {f.get('pb', 'N/A')} | ROE: {f.get('roe', 'N/A')}%")
            if f.get("revenue_growth") is not None:
                lines.append(f"     营收增长: {f['revenue_growth']:.1f}% | 毛利: {f.get('gross_margin', 'N/A')}%")
            if f.get("debt_ratio") is not None:
                lines.append(f"     负债率: {f['debt_ratio']:.1f}%")
            lines.append("")

        lines.append(f"{'='*70}")
        lines.append(f"  ⚠️ 本报告基于公开数据自动生成，仅供参考，不构成投资建议。")
        lines.append(f"{'='*70}")

        return "\n".join(lines)

    def format_ranking(self, df: pd.DataFrame) -> str:
        """格式化排名结果"""
        if df.empty:
            return "暂无数据"

        lines = []
        lines.append(f"{'='*85}")
        lines.append(f"  🐂 选股排名 (带止损止盈)")
        lines.append(f"{'='*85}")
        lines.append(f"  {'排名':<4} {'代码':<7} {'名称':<8} {'得分':<6} {'风险调整':<8} {'风险':<5} "
                     f"{'止损':<8} {'止盈':<8} {'仓位':<6}")
        lines.append(f"  {'-'*80}")

        for _, row in df.iterrows():
            rank = int(row.get("rank", 0))
            code = row.get("code", "")
            name = str(row.get("name", ""))[:6]
            score = row.get("total_score", 0)
            risk_adj = row.get("risk_adjusted_score", 0)
            risk_lv = row.get("risk_level", "?")
            sl = row.get("stop_loss", 0)
            tp = row.get("take_profit", 0)
            pos = row.get("position_pct", 0)

            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "extreme": "⛔"}
            lines.append(f"  {rank:<4} {code:<7} {name:<8} {score:<6.0f} {risk_adj:<8.1f} "
                         f"{risk_emoji.get(risk_lv, '⚪')}{risk_lv:<4} "
                         f"{sl:<8.2f} {tp:<8.2f} {pos:<6.1f}%")

        lines.append(f"{'='*85}")
        lines.append(f"  ⚠️ 仅供参考，不构成投资建议。建议结合止损位严格控制风险。")
        lines.append(f"{'='*85}")
        return "\n".join(lines)
