"""
交易计划引擎 —— 把信号升级为可执行的操盘计划
============================================
定位：系统从"数据展示工具"升级为"优秀操盘手"的核心模块。

对每只股票输出专业交易计划：
  - 评级（S/A/B/C）：信号质量分级
  - 操作（买入/加仓/持有/减仓/卖出/观望）
  - 入场区间（下沿/上沿）
  - 目标价（风险回报比 2:1 + 阻力位）
  - 止损价（ATR/均线/支撑位）
  - 建议仓位%（凯利 + 风险平价 + 单笔风险≤2%）
  - 持有周期
  - 逻辑要点 + 风险提示

组合层面：
  - 市场温度 → 总仓位上限
  - 持仓纪律（单笔风险、集中度、回撤控制）
"""
from typing import Dict, List, Optional

from analysis.decision_signals import DecisionSignals
from engine.risk_manager import RiskManager
from utils.logger import logger


class TradePlanner:
    """交易计划引擎"""

    def __init__(self, total_capital: float = 1_000_000, risk_per_trade: float = 0.02):
        """
        Args:
            total_capital: 组合总资金（默认100万）
            risk_per_trade: 单笔最大风险（默认2%）
        """
        self.total_capital = total_capital
        self.risk_per_trade = risk_per_trade
        self.risk = RiskManager()

    # ═══════════════════════════════════════════════════════════════
    # 评级
    # ═══════════════════════════════════════════════════════════════

    def _rate(self, decision: Dict, valuation: Dict) -> str:
        """信号质量评级：S/A/B/C
        - S：三维至少两维做多 + 综合≥70 + 估值不警戒
        - A：综合≥60 且至少两维偏多，或综合≥70但有瑕疵
        - B：综合 50-60 或单维做多
        - C：偏空/风险区/观望
        """
        score = decision.get("composite_score", 50)
        lt = decision.get("long_term", {}).get("signal", "观望")
        sw = decision.get("swing", {}).get("signal", "观望")
        st = decision.get("short_term", {}).get("signal", "观望")
        zone = (valuation or {}).get("zone", "价值中枢区")

        bull_count = sum(1 for s in (lt, sw, st) if s == "多")
        bear_count = sum(1 for s in (lt, sw, st) if s == "空")

        if zone == "风险警戒区":
            # 高估区无论信号多强，最多 B 级且提示风险
            return "C" if score >= 60 else "C"

        if bull_count >= 2 and score >= 70 and zone != "风险警戒区":
            return "S"
        if score >= 60 and bull_count >= 1:
            return "A"
        if score >= 50 and bull_count >= 1 and bear_count == 0:
            return "B"
        if bear_count >= 2 or score <= 40:
            return "C"
        return "B"

    # ═══════════════════════════════════════════════════════════════
    # 交易计划
    # ═══════════════════════════════════════════════════════════════

    def plan(
        self,
        code: str,
        name: str,
        kline,
        decision: Dict,
        valuation: Dict,
        current_price: Optional[float] = None,
    ) -> Dict:
        """生成单只股票交易计划（含威科夫主力行为分析）"""
        from analysis.wyckoff import analyze_wyckoff

        df = getattr(kline, "df", kline)
        price = current_price or float(df["close"].iloc[-1]) if len(df) else 0

        # 威科夫分析（主力行为）
        wyckoff = analyze_wyckoff(df)
        rating = self._rate(decision, valuation)
        # Spring 信号：教科书级抄底点 → 评级至少提升一档（C→B, B→A, A→S）
        if wyckoff.get("spring_signal") and rating != "S":
            rating = {"A": "S", "B": "A", "C": "B"}.get(rating, "B")
        action = self._action(rating, decision, price)

        # 风控参数（止损/止盈/仓位）
        stop_loss = self.risk.get_best_stop_loss(df, price)
        take_profit = self.risk.calc_take_profit(df, price, stop_loss.price)
        position = self.risk.calc_position_size(
            self.total_capital, price, stop_loss.price,
            win_rate=self._win_rate(rating), risk_per_trade_pct=self.risk_per_trade,
        )

        entry_low = round(price * 0.99, 2)   # 入场下沿（现价下1%）
        entry_high = price                    # 入场上沿（现价）

        # 持有周期（按评级/维度）
        holding = self._holding_period(decision, rating)

        logic = self._build_logic(decision, valuation, rating)
        risks = self._build_risks(decision, valuation, stop_loss)

        # 威科夫结论并入逻辑
        if wyckoff.get("spring_signal"):
            logic.insert(0, f"威科夫Spring弹簧测试：{wyckoff.get('reason', '')}")
        elif wyckoff.get("sos_signal"):
            logic.insert(0, f"威科夫SOS突破：{wyckoff.get('reason', '')}")
        elif wyckoff.get("phase") in ("吸筹中", "吸筹完成/拉升前夜", "吸筹初期"):
            logic.insert(0, f"威科夫{wyckoff.get('phase')}（吸筹评分{wyckoff.get('accumulation_score', 0)}）：{wyckoff.get('reason', '')}")

        return {
            "code": code,
            "name": name,
            "price": price,
            "rating": rating,
            "action": action,
            "entry_low": entry_low,
            "entry_high": round(entry_high, 2),
            "target_price": take_profit.price,
            "target_pct": round((take_profit.price / price - 1) * 100, 1),
            "stop_loss": stop_loss.price,
            "stop_pct": round((stop_loss.price / price - 1) * 100, 1),
            "position_pct": position.position_pct,
            "position_shares": position.suggested_shares,
            "risk_amount": round(self.total_capital * self.risk_per_trade, 0),
            "holding_period": holding,
            "win_rate": self._win_rate(rating),
            "logic": logic,
            "risks": risks,
            "decision": decision,
            "valuation": valuation,
            "wyckoff": wyckoff,
        }

    # ═══════════════════════════════════════════════════════════════
    # 辅助
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _win_rate(rating: str) -> float:
        return {"S": 0.55, "A": 0.50, "B": 0.45, "C": 0.40}.get(rating, 0.45)

    @staticmethod
    def _action(rating: str, decision: Dict, price: float) -> str:
        score = decision.get("composite_score", 50)
        if rating == "S":
            return "买入/加仓"
        if rating == "A":
            return "买入"
        if rating == "B":
            return "持有/试仓"
        # C 级
        if score <= 40:
            return "卖出/回避"
        return "观望"

    @staticmethod
    def _holding_period(decision: Dict, rating: str) -> str:
        lt = decision.get("long_term", {}).get("signal", "观望")
        if rating == "S" and lt == "多":
            return "中线（4-12周）"
        if rating in ("S", "A"):
            return "波段（1-4周）"
        if rating == "B":
            return "短线（3-10日）"
        return "观望"

    @staticmethod
    def _build_logic(decision: Dict, valuation: Dict, rating: str) -> List[str]:
        logic = []
        lt = decision.get("long_term", {})
        sw = decision.get("swing", {})
        st = decision.get("short_term", {})
        if lt.get("signal") == "多":
            logic.append(f"长线趋势偏多（{lt.get('reason', '')[:40]}）")
        if sw.get("signal") == "多":
            logic.append(f"波段信号偏多（{sw.get('reason', '')[:40]}）")
        if st.get("signal") == "多":
            logic.append(f"短线动能偏多（{st.get('reason', '')[:40]}）")
        if lt.get("signal") == "空":
            logic.append("长线趋势偏空，反弹仅限短线")
        zone = (valuation or {}).get("zone", "")
        if zone:
            logic.append(f"估值位于{zone}")
        if rating == "S":
            logic.append("多周期共振 + 估值配合 → 高确定性机会")
        elif rating == "C":
            logic.append("信号偏弱或估值偏高，仅作观察")
        return logic

    @staticmethod
    def _build_risks(decision: Dict, valuation: Dict, stop_loss) -> List[str]:
        risks = []
        vol = decision.get("swing", {}).get("score", 50)
        zone = (valuation or {}).get("zone", "")
        if zone == "风险警戒区":
            risks.append("估值处于历史高位，谨防回调")
        if stop_loss and stop_loss.distance_pct and stop_loss.distance_pct > 12:
            risks.append(f"止损距离较大（{stop_loss.distance_pct:.1f}%），仓位需更保守")
        if vol < 35:
            risks.append("波段信号偏弱，可能震荡")
        if not risks:
            risks.append("严格执行止损纪律，单笔风险≤2%")
        return risks

    # ═══════════════════════════════════════════════════════════════
    # 组合层：市场温度 → 总仓位建议
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def portfolio_position(zone: str) -> Dict:
        """市场温度 → 组合总仓位建议"""
        mapping = {
            "安全边界区": {"total_position": "60-80%", "note": "市场低位，可分批布局低估优质标的"},
            "价值中枢区": {"total_position": "40-60%", "note": "多空均衡，精选个股，维持中性仓位"},
            "风险警戒区": {"total_position": "20-40%", "note": "高位过热，控制仓位，只做强势股快进快出"},
            "极端区": {"total_position": "≤20%", "note": "极端行情，防守为主，等待方向"},
        }
        return mapping.get(zone, {"total_position": "40-60%", "note": "维持中性仓位"})


def plan_stock(code: str, name: str = "", capital: float = 1_000_000) -> Dict:
    """便捷函数：单只股票完整交易计划（数据+决策+估值+计划）"""
    from data.data_utils import get_best_fetcher
    from analysis.valuation_space import ValuationSpace
    import time

    fetcher = get_best_fetcher()
    kl = fetcher.get_history_kline(code, "daily",
                                   time.strftime("%Y%m%d", time.localtime(time.time() - 600 * 86400)),
                                   time.strftime("%Y%m%d"), "qfq")
    if kl is None or kl.data_count < 60:
        return {"code": code, "name": name or code, "error": "K线数据不足", "plan": None}

    decision = DecisionSignals().comprehensive(kl)
    valuation = ValuationSpace().analyze(code)
    planner = TradePlanner(total_capital=capital)
    plan = planner.plan(code, name or getattr(kl, "name", "") or code, kl, decision, valuation)
    return {"code": code, "name": plan["name"], "plan": plan}
