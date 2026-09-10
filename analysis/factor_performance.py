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
        """统计交易计划评级绩效 —— 严格按「快照日 + N 交易日」取收盘价（可复现）。

        每笔样本计算：
          ret_tn   : 快照日收盘基准 → 快照日+N 交易日收盘 的收益（%）
          mfe      : 区间最大有利偏移（区间最高 / 基准 - 1）
          mae      : 区间最大不利偏移（区间最低 / 基准 - 1）
          hit      : 先到目标(target_price) 还是先到止损(stop_loss)
        未满 N 交易日的样本记为 pending（待观察），不计入统计。
        """
        rows = snapshot_store.query_snapshots(trade_date=trade_date, snapshot_type="plan", limit=limit)
        if not rows:
            return {"available": False, "msg": "无快照数据（请先通过 /api/ops/plan 生成并保存快照）"}

        from data.data_utils import get_best_fetcher
        fetcher = get_best_fetcher()

        groups: Dict[str, List[Dict]] = {}
        evaluated = 0
        pending = 0

        for r in rows:
            p = r.get("payload", {})
            rating = p.get("rating", "-")
            code = r.get("code", "")
            snap_date = str(r.get("trade_date", ""))[:10]
            entry_price = p.get("price") or p.get("entry_low")
            if not code or not entry_price or not snap_date:
                continue

            try:
                # 拉足够长的 K 线：快照日前 15 天 → 今天
                start_ms = time.mktime(time.strptime(snap_date, "%Y-%m-%d")) - 15 * 86400
                kl = fetcher.get_history_kline(
                    code, "daily",
                    time.strftime("%Y%m%d", time.localtime(start_ms)),
                    time.strftime("%Y%m%d"), "qfq")
                if kl is None:
                    continue
                df = getattr(kl, "df", kl)
                if df is None or df.empty or "date" not in df.columns:
                    continue

                # 定位快照日在 df 中的位置（或其后第一个交易日）
                dates = [str(d)[:10] for d in df["date"].tolist()]
                idx = None
                for i, d in enumerate(dates):
                    if d >= snap_date:
                        idx = i
                        break
                if idx is None:
                    continue
                base = float(entry_price)
                if base <= 0:
                    continue

                target_idx = idx + self.horizon
                if target_idx >= len(df):
                    pending += 1  # 未满 N 交易日，待观察
                    continue

                close_tn = float(df["close"].iloc[target_idx])
                if close_tn <= 0:
                    continue
                ret = (close_tn / base - 1) * 100

                # 区间（快照日次日起至 T+N）最高/最低 → MFE/MAE
                seg = df.iloc[idx + 1: target_idx + 1]
                hi = float(seg["high"].max()) if "high" in seg.columns and len(seg) else close_tn
                lo = float(seg["low"].min()) if "low" in seg.columns and len(seg) else close_tn
                mfe = (hi / base - 1) * 100
                mae = (lo / base - 1) * 100

                # 先到目标还是先到止损（按日线近似：逐日判断 close 触发）
                hit = None
                tgt = p.get("target_price")
                stop = p.get("stop_loss")
                if tgt or stop:
                    for _, row in seg.iterrows():
                        c = float(row["close"])
                        if stop and c <= float(stop):
                            hit = "stop"
                            break
                        if tgt and c >= float(tgt):
                            hit = "target"
                            break

                groups.setdefault(rating, []).append(
                    {"ret": ret, "mfe": mfe, "mae": mae, "hit": hit})
                evaluated += 1
            except Exception as e:
                logger.warning(f"绩效统计 {code} 失败: {e}")

        if not groups:
            return {"available": False,
                    "msg": "无有效样本（K线不可用或全部待观察）",
                    "evaluated": evaluated, "pending": pending}

        result = {}
        for rating, items in groups.items():
            arr = pd.Series([x["ret"] for x in items])
            mfes = pd.Series([x["mfe"] for x in items])
            maes = pd.Series([x["mae"] for x in items])
            win_rate = float((arr > 0).mean() * 100)
            wins = arr[arr > 0]
            losses = arr[arr <= 0]
            avg_win = float(wins.mean()) if len(wins) else 0
            avg_loss = float(abs(losses.mean())) if len(losses) else 0
            hit_t = sum(1 for x in items if x["hit"] == "target")
            hit_s = sum(1 for x in items if x["hit"] == "stop")
            result[rating] = {
                "samples": len(items),
                "win_rate": round(win_rate, 1),
                "avg_return": round(float(arr.mean()), 2),
                "profit_loss_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
                "max_loss": round(float(arr.min()), 2),
                "avg_mfe": round(float(mfes.mean()), 2),
                "avg_mae": round(float(maes.mean()), 2),
                "hit_target": hit_t,
                "hit_stop": hit_s,
            }
        ordered = {}
        for k in ("S", "A", "B", "C", "-"):
            if k in result:
                ordered[k] = result[k]
        return {"available": True, "horizon_days": self.horizon,
                "evaluated": evaluated, "pending": pending, "ratings": ordered,
                "method": f"T+{self.horizon} 交易日收盘（快照日基准，MFE/MAE 区间统计）",
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
