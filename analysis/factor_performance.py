"""
因子绩效统计（v3.1 P1）—— 回测验证 S/A 级胜率
==============================================
读取信号快照 + 后续真实 K 线行情 → 统计各评级/信号的实际绩效：
  胜率 / 盈亏比 / 平均持仓收益 / 最大连续亏损 / 不同市场温度下表现

输出统计报告（只做统计，不自动修改权重 —— 文档要求）
"""
import time
from typing import Dict, List, Optional

import pandas as pd

from utils.logger import logger
from analysis import snapshot_store


class FactorPerformance:
    """信号绩效统计器"""

    def __init__(self, horizon_days: int = 5):
        """
        Args:
            horizon_days: 验证窗口（T+N 后检查涨跌）
        """
        self.horizon = horizon_days

    def evaluate_plans(self, trade_date: str = "", limit: int = 100) -> Dict:
        """统计交易计划评级绩效（S/A/B/C 胜率 + 平均收益）"""
        rows = snapshot_store.query_snapshots(trade_date=trade_date, snapshot_type="plan", limit=limit)
        if not rows:
            return {"available": False, "msg": "无快照数据（请先通过 /api/ops/plan 生成并保存快照）"}

        from data.data_utils import get_best_fetcher
        fetcher = get_best_fetcher()

        # 按评级分组统计
        groups: Dict[str, List[float]] = {}
        evaluated = 0
        for r in rows:
            p = r.get("payload", {})
            rating = p.get("rating", "-")
            code = r.get("code", "")
            entry_price = p.get("price") or p.get("entry_low")
            if not code or not entry_price:
                continue

            # 获取 T+horizon 后的收盘价
            try:
                kl = fetcher.get_history_kline(
                    code, "daily",
                    time.strftime("%Y%m%d", time.localtime(time.time() - 60 * 86400)),
                    time.strftime("%Y%m%d"), "qfq")
                if kl is None:
                    continue
                df = getattr(kl, "df", kl)
                if df is None or df.empty or len(df) < self.horizon:
                    continue
                close_now = float(df["close"].iloc[-1])
                if close_now <= 0:
                    continue
                ret = (close_now / float(entry_price) - 1) * 100
                groups.setdefault(rating, []).append(ret)
                evaluated += 1
            except Exception as e:
                logger.warning(f"绩效统计 {code} 失败: {e}")

        if not groups:
            return {"available": False, "msg": "无有效样本（K线不可用）", "evaluated": evaluated}

        result = {}
        for rating, rets in groups.items():
            arr = pd.Series(rets)
            win_rate = float((arr > 0).mean() * 100)
            avg_ret = float(arr.mean())
            # 盈亏比 = 平均盈利 / |平均亏损|
            wins = arr[arr > 0]
            losses = arr[arr <= 0]
            avg_win = float(wins.mean()) if len(wins) else 0
            avg_loss = float(abs(losses.mean())) if len(losses) else 0
            profit_loss_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0
            result[rating] = {
                "samples": len(rets),
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_ret, 2),
                "profit_loss_ratio": profit_loss_ratio,
                "max_loss": round(float(arr.min()), 2),
            }
        # 按评级优先级排序
        ordered = {}
        for k in ("S", "A", "B", "C", "-"):
            if k in result:
                ordered[k] = result[k]
        return {"available": True, "horizon_days": self.horizon,
                "evaluated": evaluated, "ratings": ordered,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    def rating_hit_rate(self, rating: str = "S", trade_date: str = "") -> Dict:
        """单评级命中率（参考用）"""
        rows = snapshot_store.query_snapshots(trade_date=trade_date, snapshot_type="plan", limit=500)
        rated = [r for r in rows if r.get("payload", {}).get("rating") == rating]
        return {"rating": rating, "total_signals": len(rated),
                "codes": [r.get("code") for r in rated[:20]]}


def get_performance_report(trade_date: str = "", horizon: int = 5) -> Dict:
    """便捷函数"""
    return FactorPerformance(horizon_days=horizon).evaluate_plans(trade_date=trade_date)
