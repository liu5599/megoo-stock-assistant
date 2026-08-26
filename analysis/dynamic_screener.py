"""
动态选股引擎 —— 解决"每次选出一模一样"的静态问题
================================================
优秀操盘手关注的动态维度：
  1. 情绪周期：涨停家数/连板高度/炸板率 → 市场风险偏好（进攻/正常/冰点）
  2. 题材轮动：今日涨停行业 vs 昨日涨停行业 → 新晋主线（轮动启动信号）
  3. 底部吸筹：龙虎榜当日下跌但资金净买入 → 资金低位建仓（提前抄底信号）
  4. 主线龙头：连板高度 + 封板资金 → 情绪龙头

每日输出随市场变化，杜绝"每天同一批股票"。
数据源全部为稳定免费接口（东财涨停池/龙虎榜/乐咕）。
"""
import time
from typing import Dict, List, Optional

import pandas as pd

from utils.logger import logger
from analysis._cache import ttl_cache


# ═══════════════════════════════════════════════════════════════
# 数据获取（复用稳定源）
# ═══════════════════════════════════════════════════════════════

@ttl_cache(300)
def _fetch_zt_today() -> Optional[pd.DataFrame]:
    import akshare as ak
    try:
        return ak.stock_zt_pool_em()
    except Exception as e:
        logger.warning(f"今日涨停池获取失败: {e}")
        return None


@ttl_cache(3600)
def _fetch_zt_previous(date: str = "") -> Optional[pd.DataFrame]:
    import akshare as ak
    if not date:
        # 最近一个交易日
        d = pd.Timestamp.now()
        for _ in range(7):
            d = d - pd.Timedelta(days=1)
            if d.weekday() < 5:
                date = d.strftime("%Y%m%d")
                break
    try:
        return ak.stock_zt_pool_previous_em(date=date)
    except Exception as e:
        logger.warning(f"昨日涨停池获取失败: {e}")
        return None


@ttl_cache(3600)
def _fetch_lhb() -> Optional[pd.DataFrame]:
    import akshare as ak
    try:
        end = pd.Timestamp.now()
        start = end - pd.Timedelta(days=6)
        return ak.stock_lhb_detail_em(
            start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    except Exception as e:
        logger.warning(f"龙虎榜获取失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# 动态选股引擎
# ═══════════════════════════════════════════════════════════════

class DynamicScreener:
    """动态选股引擎 —— 情绪周期 + 题材轮动 + 底部吸筹 + 主线龙头"""

    def __init__(self):
        self.zt = _fetch_zt_today()
        self.zt_prev = _fetch_zt_previous()
        self.lhb = _fetch_lhb()

    # ---------------- 1. 情绪周期 ----------------

    def get_market_cycle(self) -> Dict:
        """情绪周期：涨停家数、连板高度、炸板率 → 风险偏好"""
        cycle = {
            "limit_up_count": 0, "max_boards": 0,
            "boards_3plus": 0, "break_rate": 0,
            "cycle_label": "数据不足", "cycle_desc": "",
        }
        if self.zt is None or self.zt.empty:
            return cycle

        zt = self.zt
        limit_up = len(zt)
        cycle["limit_up_count"] = limit_up

        # 连板高度
        boards = pd.to_numeric(zt.get("连板数", 0), errors="coerce").fillna(1)
        cycle["max_boards"] = int(boards.max()) if len(boards) else 0
        cycle["boards_3plus"] = int((boards >= 3).sum())

        # 炸板率
        if "炸板次数" in zt.columns:
            breaks = pd.to_numeric(zt["炸板次数"], errors="coerce").fillna(0)
            cycle["break_rate"] = round(float((breaks > 0).mean() * 100), 1)

        # 昨日对比（情绪变化）
        prev_count = len(self.zt_prev) if self.zt_prev is not None else 0
        change = limit_up - prev_count

        if limit_up >= 80:
            cycle["cycle_label"] = "情绪亢奋"
            cycle["cycle_desc"] = f"涨停{limit_up}家（较昨日{change:+d}），短线亢奋，注意高位风险"
        elif limit_up >= 50:
            cycle["cycle_label"] = "情绪活跃"
            cycle["cycle_desc"] = f"涨停{limit_up}家（较昨日{change:+d}），市场活跃，题材机会多"
        elif limit_up >= 25:
            cycle["cycle_label"] = "情绪正常"
            cycle["cycle_desc"] = f"涨停{limit_up}家（较昨日{change:+d}），结构行情，精选个股"
        else:
            cycle["cycle_label"] = "情绪冰点"
            cycle["cycle_desc"] = f"涨停仅{limit_up}家，情绪冰点，等待冰点转折"
        return cycle

    # ---------------- 2. 题材轮动 ----------------

    def get_rotation(self, top_n: int = 8) -> List[Dict]:
        """题材轮动：今日涨停行业 vs 昨日涨停行业 → 新晋方向"""
        if self.zt is None or self.zt.empty:
            return []

        def _industry_counter(df):
            if df is None or df.empty or "所属行业" not in df.columns:
                return {}
            c = {}
            for b in df["所属行业"].dropna():
                c[b] = c.get(b, 0) + 1
            return c

        today = _industry_counter(self.zt)
        prev = _industry_counter(self.zt_prev)

        rows = []
        for ind, cnt in sorted(today.items(), key=lambda x: -x[1]):
            prev_cnt = prev.get(ind, 0)
            rows.append({
                "industry": ind,
                "limit_up_count": cnt,
                "prev_count": prev_cnt,
                "is_new": prev_cnt == 0,           # 新晋方向
                "increasing": cnt > prev_cnt,       # 加强方向
                "heat": min(cnt * 10, 100),
            })
        rows.sort(key=lambda x: (x["is_new"], x["increasing"], x["heat"]), reverse=True)
        return rows[:top_n]

    # ---------------- 3. 底部吸筹池（提前抄底） ----------------

    def get_bottom_fishing(self, top_n: int = 10) -> List[Dict]:
        """底部吸筹：龙虎榜当日下跌但资金净买入大 → 资金低位建仓"""
        if self.lhb is None or self.lhb.empty:
            return []

        df = self.lhb.copy()
        for col in ("涨跌幅", "龙虎榜净买额"):
            if col not in df.columns:
                return []
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 当日下跌（涨跌幅<0）但净买额>0 → 资金逆势吸筹
        fish = df[(df["涨跌幅"] < 0) & (df["龙虎榜净买额"] > 0)]
        if fish.empty:
            # 降级：涨幅<3% 且净买额大（低位温和吸筹）
            fish = df[(df["涨跌幅"] < 3) & (df["龙虎榜净买额"] > 0)]

        fish = fish.sort_values("龙虎榜净买额", ascending=False).head(top_n)
        rows = []
        for _, r in fish.iterrows():
            rows.append({
                "code": r.get("代码", ""),
                "name": r.get("名称", ""),
                "pct_chg": round(float(r.get("涨跌幅", 0) or 0), 2),
                "net_buy": round(float(r.get("龙虎榜净买额", 0) or 0) / 1e8, 2),
                "reason": str(r.get("上榜原因", ""))[:30],
                "signal": "资金低位吸筹",
            })
        return rows

    # ---------------- 4. 主线龙头池 ----------------

    def get_theme_leaders(self, top_n: int = 8) -> List[Dict]:
        """主线龙头：连板高度 + 封板资金"""
        if self.zt is None or self.zt.empty:
            return []

        zt = self.zt.copy()
        for col in ("连板数", "封板资金"):
            if col in zt.columns:
                zt[col] = pd.to_numeric(zt[col], errors="coerce").fillna(0)
        if "连板数" not in zt.columns:
            return []

        zt = zt.sort_values(["连板数", "封板资金"], ascending=False)
        rows = []
        for _, r in zt.head(top_n).iterrows():
            rows.append({
                "code": r.get("代码", ""),
                "name": r.get("名称", ""),
                "boards": int(r.get("连板数", 0) or 0),
                "seal_amount": round(float(r.get("封板资金", 0) or 0) / 1e8, 2),
                "industry": r.get("所属行业", ""),
                "tag": "空间龙头" if int(r.get("连板数", 0) or 0) >= 5 else
                       ("高标" if int(r.get("连板数", 0) or 0) >= 3 else "首板"),
            })
        return rows

    # ---------------- 汇总 ----------------

    def run(self) -> Dict:
        """今日策略池（每日随市场变化）"""
        return {
            "cycle": self.get_market_cycle(),
            "rotation": self.get_rotation(),
            "bottom_fishing": self.get_bottom_fishing(),
            "theme_leaders": self.get_theme_leaders(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def get_dynamic_screener() -> Dict:
    """便捷函数"""
    return DynamicScreener().run()
