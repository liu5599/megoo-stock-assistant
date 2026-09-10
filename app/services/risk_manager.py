"""
风控委员会（v4.1 P0）—— 决策层的硬约束，拥有一票否决权
====================================================================
评审指出的核心缺陷：AI 只分析不拦截。本模块在 ask_agent 产出决策后强制过闸，
对违反纪律的建议直接否决或缩减仓位 —— AI 无权推翻。

规则（可被外部 portfolio/market 状态覆盖）：
  R1 总仓位红线：现有总仓位 ≥ 90% → 否决任何买入
  R2 集中度红线：单票占比 ≥ 20% → 否决加仓该票
  R3 大盘风控：市场 regime 为防守/冰点 → 买入仓位上限压至 30%
  R4 纪律红线：买入建议缺止损价 → 否决（无止损不交易）
  R5 单笔风险：单笔风险敞口 > 总资金 2% → 按 2% 反推缩减仓位

对外接口：
  check(decision, portfolio, market) → {approved, action, position_pct, vetoes:[], adjustments:[]}
"""
from typing import Dict, List, Optional

from utils.logger import logger

MAX_TOTAL_POSITION = 0.90       # R1 总仓位红线
MAX_SINGLE_POSITION = 0.20      # R2 单票集中度红线
DEFENSIVE_POSITION_CAP = 0.10   # R3 防守市单笔买入仓位上限（须低于 R2 的20%才有效）
MAX_RISK_PER_TRADE = 0.02       # R5 单笔风险上限
DEFENSIVE_REGIMES = {"防守", "冰点", "退潮", "risk_off"}


def check(decision: Dict,
          portfolio: Optional[Dict] = None,
          market: Optional[Dict] = None) -> Dict:
    """对单条决策过风控。

    decision: {action: buy/sell/hold, position_ratio: 0-1, stop_loss: float|None,
               price: float|None, code, name}
    portfolio: {total_position: 0-1, positions: {code: {ratio: 0-1}}, total_capital: float}
    market: {regime: str, index_below_ma60: bool}

    return: {approved, action, position_ratio, vetoes, adjustments}
    """
    portfolio = portfolio or {}
    market = market or {}
    vetoes: List[str] = []
    adjustments: List[str] = []

    action = str(decision.get("action", "hold")).lower()
    position_ratio = float(decision.get("position_ratio") or 0.0)
    stop_loss = decision.get("stop_loss")
    price = decision.get("price")
    code = decision.get("code", "")
    name = decision.get("name", code)

    # 非买入建议：仅记录，不拦截（卖出/持有应放行，避免阻碍减仓）
    if action not in ("buy", "买入", "add", "加仓"):
        return {"approved": True, "action": action,
                "position_ratio": position_ratio,
                "vetoes": [], "adjustments": []}

    # R4 无止损不交易（纪律红线，最先拦）
    if not stop_loss or (price and float(stop_loss) >= float(price)):
        vetoes.append(f"R4 纪律红线：{name} 买入建议无有效止损价（止损{stop_loss} ≥ 现价{price}）—— 无止损不交易")

    # R1 总仓位红线
    total_pos = float(portfolio.get("total_position") or 0.0)
    if total_pos >= MAX_TOTAL_POSITION:
        vetoes.append(f"R1 总仓位红线：当前总仓位 {total_pos:.0%} ≥ {MAX_TOTAL_POSITION:.0%}，禁止买入")

    # R2 集中度红线
    positions = portfolio.get("positions") or {}
    cur_ratio = 0.0
    if code in positions:
        cur_ratio = float((positions[code] or {}).get("ratio") or 0.0)
    if cur_ratio >= MAX_SINGLE_POSITION:
        vetoes.append(f"R2 集中度红线：{name} 已占 {cur_ratio:.0%} ≥ {MAX_SINGLE_POSITION:.0%}，禁止加仓")
    elif cur_ratio + position_ratio > MAX_SINGLE_POSITION:
        new_ratio = MAX_SINGLE_POSITION - cur_ratio
        adjustments.append(f"R2 集中度：{name} 加仓后占比将超 {MAX_SINGLE_POSITION:.0%}，仓位缩减至 {new_ratio:.0%}")
        position_ratio = max(0.0, new_ratio)

    # R3 大盘风控
    regime = str(market.get("regime", "") or "")
    if regime in DEFENSIVE_REGIMES and position_ratio > DEFENSIVE_POSITION_CAP:
        adjustments.append(f"R3 大盘风控：市场处于「{regime}」，买入仓位上限压至 {DEFENSIVE_POSITION_CAP:.0%}")
        position_ratio = DEFENSIVE_POSITION_CAP

    # R5 单笔风险敞口
    if stop_loss and price and float(price) > 0:
        risk_pct = abs(float(price) - float(stop_loss)) / float(price)
        total_capital = float(portfolio.get("total_capital") or 1_000_000)
        risk_amount_ratio = risk_pct * position_ratio
        if risk_amount_ratio > MAX_RISK_PER_TRADE:
            capped = MAX_RISK_PER_TRADE / risk_pct if risk_pct > 0 else position_ratio
            adjustments.append(
                f"R5 单笔风险：原始风险敞口 {risk_amount_ratio:.2%} > {MAX_RISK_PER_TRADE:.0%}，"
                f"仓位缩减至 {capped:.0%}（单笔风险≈{MAX_RISK_PER_TRADE:.0%}总资金）")
            position_ratio = min(position_ratio, capped)

    approved = len(vetoes) == 0
    if not approved:
        position_ratio = 0.0
        logger.info(f"🛡️ 风控否决 {name}: {' | '.join(vetoes)}")
    elif adjustments:
        logger.info(f"🛡️ 风控调整 {name}: {' | '.join(adjustments)}")

    return {
        "approved": approved,
        "action": action if approved else "hold",
        "position_ratio": round(position_ratio, 4),
        "vetoes": vetoes,
        "adjustments": adjustments,
    }
