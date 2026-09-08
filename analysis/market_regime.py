"""
盘面定性引擎（真操盘手内核）—— 判断「今天能不能干、干几成」
==========================================================
补温度计盲区：温度计是「估值贵不贵」(慢变量)，regime 是「今天赚不赚钱」(快变量)。
79 涨停 0 跌停的日子温度仍可能 55 → 温度计叫中性，regime 必须喊进攻。

输入复用已有数据（activity 涨跌停家数 + bull_bear 主力资金），不新增数据源。
决策树按风险确定性排序：冰点 > 防守 > 过热 > 进攻 > 均衡。
"""
from typing import Dict, Optional


def _num(d: Dict, key, default: float = 0.0) -> float:
    try:
        v = d.get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def compute_regime(activity: Optional[Dict] = None,
                   bull_bear: Optional[Dict] = None) -> Dict:
    """输出盘面定性。数据不足 → 未知(降级)，绝不冒充真实判断。"""
    activity = activity or {}
    bull_bear = bull_bear or {}

    up = _num(activity, "上涨")
    down = _num(activity, "下跌")
    limit_up = _num(activity, "涨停", default=-1)
    limit_down = _num(activity, "跌停", default=-1)
    # 真实涨停缺省时用涨停总数（乐咕 activity 无真实涨停字段时兜底）
    if "真实涨停" in activity and _num(activity, "真实涨停") >= 0:
        real_limit_up = _num(activity, "真实涨停")
        if real_limit_up > 0:
            limit_up = real_limit_up
    net_total = bull_bear.get("net_total")  # 主力净流入(亿)，缺失不阻塞

    reasons: list = []
    has_breadth = (up + down) > 0
    up_down_ratio = (up / down) if down > 0 else (9.9 if has_breadth else None)

    def _r(s: str):
        reasons.append(s)

    # ── 数据不足 → 未知，不瞎判（降级=降级，这是纪律） ──
    if not has_breadth and limit_up < 0:
        return {
            "regime": "未知", "position_max": 0.5, "advice": "盘面数据不足，暂无法定性，观望为主",
            "reasons": ["涨跌/涨跌停数据缺失"], "temperature_like": None,
        }

    # ── 1. 冰点：恐慌杀跌 ──
    if limit_down >= 100 or (limit_down >= 50 and 0 < limit_up < 30):
        if limit_down >= 100:
            _r(f"跌停 {limit_down:.0f} 家，恐慌杀跌")
        else:
            _r(f"跌停 {limit_down:.0f} 家 vs 涨停仅 {limit_up:.0f} 家")
        return {
            "regime": "冰点", "position_max": 0.1,
            "advice": "恐慌杀跌日：不抄飞刀，等跌停家数收敛再动手；已空仓的耐心等企稳信号",
            "reasons": reasons, "up_down_ratio": up_down_ratio,
        }

    # ── 2. 防守：亏钱效应主导 ──
    if limit_down >= 30 or (10 <= limit_down < 30 and limit_up < 30) \
            or (up_down_ratio is not None and up_down_ratio <= 0.4):
        if limit_down >= 30:
            _r(f"跌停 {limit_down:.0f} 家，亏钱效应扩散")
        elif up_down_ratio is not None:
            _r(f"涨跌比 {up_down_ratio:.2f}，跌多涨少")
        _r("防守日：总仓 ≤3 成或空仓，只做最强逆势龙头")
        return {
            "regime": "防守", "position_max": 0.3,
            "advice": "亏钱效应主导：防守为主，总仓不超 3 成，不做弱势票，等跌停收敛",
            "reasons": reasons, "up_down_ratio": up_down_ratio,
        }

    # ── 3. 过热：亢奋防分歧 ──
    if limit_up >= 120 and (limit_down <= 20 or limit_down < 0):
        _r(f"涨停 {limit_up:.0f} 家，情绪亢奋")
        _r("高位防分歧：不追后排，只做最强主线龙头，封单弱就走")
        return {
            "regime": "过热", "position_max": 0.5,
            "advice": "情绪亢奋近高潮：不追高、不满仓，只做最强主线核心，谨防天地板分歧",
            "reasons": reasons, "up_down_ratio": up_down_ratio,
        }

    # ── 4. 进攻：赚钱效应 + 主线明确 ──
    if limit_up >= 50 and (limit_down <= 10 or limit_down < 0) \
            and (up_down_ratio is None or up_down_ratio >= 1.2):
        if limit_up >= 50:
            _r(f"涨停 {limit_up:.0f} 家、跌停 {limit_down:.0f} 家，赚钱效应强")
        if up_down_ratio is not None:
            _r(f"涨跌比 {up_down_ratio:.2f}")
        if net_total is not None:
            _r(f"主力净流入 {net_total:.0f} 亿" if net_total > 0 else f"主力净流出 {abs(net_total):.0f} 亿")
            if net_total <= 0:
                _r("主力净流出：进攻仓位压低一档，只做题材龙头")
                return {
                    "regime": "进攻", "position_max": 0.5,
                    "advice": f"赚钱效应强但主力净流出：可做主线龙头，仓位压到 5 成，不碰跟风票",
                    "reasons": reasons, "up_down_ratio": up_down_ratio,
                }
        _r("进攻日：主线内选最强，6~7 成仓")
        return {
            "regime": "进攻", "position_max": 0.7,
            "advice": "赚钱效应强、主线明确：6~7 成仓进攻，只在主线上做最强分歧买点，不及预期次日就走",
            "reasons": reasons, "up_down_ratio": up_down_ratio,
        }

    # ── 5. 均衡：结构性 ──
    if has_breadth:
        if up_down_ratio is not None:
            _r(f"涨跌比 {up_down_ratio:.2f}，多空拉锯")
        _r("均衡日：精选个股，4~5 成仓，不满仓不空仓")
    return {
        "regime": "均衡", "position_max": 0.5,
        "advice": "多空均衡：精选个股做结构性机会，4~5 成仓，等方向选择再加减",
        "reasons": reasons, "up_down_ratio": up_down_ratio,
    }


if __name__ == "__main__":
    # 自检：真盘手阈值验证（今天实况 → 必须进攻；极端日 → 必须防守/冰点）
    today = {"上涨": 3212, "下跌": 1875, "涨停": 79, "真实涨停": 69, "跌停": 0, "平盘": 120}
    bb = {"bull_count": 100, "bear_count": 0, "net_total": 247.12, "ratio": 1.0}
    assert compute_regime(today, bb)["regime"] == "进攻", "79涨停0跌停+主力流入 必须是进攻"
    assert compute_regime(today, {})["regime"] == "进攻"
    crash = {"上涨": 300, "下跌": 4800, "涨停": 15, "跌停": 320, "平盘": 30}
    assert compute_regime(crash, {})["regime"] == "冰点"
    weak = {"上涨": 900, "下跌": 4200, "涨停": 20, "跌停": 45, "平盘": 30}
    assert compute_regime(weak, {})["regime"] == "防守"
    mania = {"上涨": 4500, "下跌": 400, "涨停": 160, "跌停": 3, "平盘": 20}
    assert compute_regime(mania, {})["regime"] == "过热"
    assert compute_regime({}, {})["regime"] == "未知"
    print("✅ regime 自检通过")
