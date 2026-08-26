"""
资金追踪（辨多空）— 对标「指南针主力资金/敢死队资金/多空资金/龙虎榜」
==================================================================
核心能力：
  1. 主力资金：个股主力净流入排行（今日/3日/5日）—— 指南针「主力资金」
  2. 敢死队资金：涨停+高换手+主力大幅流入的游资活跃股 —— 指南针「敢死队资金」
  3. 多空资金：主力净流入方向统计 → 市场多空对比 —— 指南针「多空资金」
  4. 龙虎榜：机构/游资席位动向 —— 指南针「盘龙虎榜」

数据源：akshare（东方财富资金流 + 龙虎榜）
"""
import time
from typing import Dict, List, Optional

import pandas as pd

from utils.logger import logger
from analysis._cache import ttl_cache


# 东财资金流接口熔断：失败一次后本次进程内直接降级（东财风控触发后重试无意义）
_eastmoney_circuit_open = False


def _safe_call(func, *args, retries: int = 1, **kwargs):
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < retries:
                logger.warning(f"akshare调用失败({attempt+1}/{retries+1}): {e}，重试...")
                time.sleep(1.0)
            else:
                logger.error(f"akshare调用最终失败: {e}")
                return None


@ttl_cache(300)
def fetch_fund_flow_rank(indicator: str = "今日") -> Optional[pd.DataFrame]:
    """个股资金流排行；东财直连(突破限频) → Tushare(付费兜底) → akshare → 降级"""
    global _eastmoney_circuit_open

    # 1. 东财直连（Cookie预热+域名轮换，限频期间也能用）
    try:
        from data.eastmoney_direct import fetch_stock_flow_rank, reset_circuit
        if _eastmoney_circuit_open:
            reset_circuit()  # 直连层有自己的熔断，允许重试
        df = fetch_stock_flow_rank(100)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.warning(f"东财直连资金流失败: {e}")

    # 2. Tushare 优先（配置了 token 且当日数据已更新时）
    try:
        from data.tushare_fetcher import tushare_enabled, fetch_moneyflow
        if tushare_enabled():
            import time as _t
            df = fetch_moneyflow(_t.strftime("%Y%m%d"))
            if df is not None and not df.empty:
                # 标准化为东财 rank 兼容格式
                df = df.sort_values("main_net", ascending=False)
                df["代码"] = df["code"].str[-6:]
                df["名称"] = ""
                df["今日主力净流入-净额"] = df["main_net"]
                df["今日涨跌幅"] = 0.0
                return df[["代码", "名称", "今日涨跌幅", "今日主力净流入-净额"]]
    except Exception as e:
        logger.warning(f"Tushare资金流失败: {e}")

    # 3. akshare 东财接口（熔断保护）
    if _eastmoney_circuit_open:
        return None
    ak = __import__("akshare", fromlist=["stock_individual_fund_flow_rank"])
    df = _safe_call(ak.stock_individual_fund_flow_rank, indicator=indicator)
    if df is None:
        _eastmoney_circuit_open = True
        logger.info("akshare东财资金流接口熔断开启，后续请求直接降级")
    return df


def fetch_lhb_detail(start_date: str = "", end_date: str = "") -> Optional[pd.DataFrame]:
    """龙虎榜详情（缓存1小时）；Tushare(付费兜底) → 东财"""
    # 1. Tushare 优先
    try:
        from data.tushare_fetcher import tushare_enabled, fetch_top_list
        if tushare_enabled():
            import time as _t
            df = fetch_top_list(_t.strftime("%Y%m%d"))
            if df is not None and not df.empty:
                df["代码"] = df["code"].str[-6:]
                df["龙虎榜净买额"] = df["net_amount"]
                df["上榜原因"] = df.get("reason", "")
                df["涨跌幅"] = df.get("pct_change", 0)
                return df[["代码", "名称", "龙虎榜净买额", "上榜原因", "涨跌幅"]]
    except Exception as e:
        logger.warning(f"Tushare龙虎榜失败: {e}")

    # 2. 东财
    if not start_date:
        end = pd.Timestamp.now()
        start = end - pd.Timedelta(days=6)
        start_date = start.strftime("%Y%m%d")
        end_date = end.strftime("%Y%m%d")
    ak = __import__("akshare", fromlist=["stock_lhb_detail_em"])
    df = _safe_call(ak.stock_lhb_detail_em, start_date=start_date, end_date=end_date)
    return df


def fetch_lhb_stock_detail_date(stock: str, date: str) -> Optional[pd.DataFrame]:
    """龙虎榜个股明细（席位）"""
    ak = __import__("akshare", fromlist=["stock_lhb_stock_detail_em"])
    df = _safe_call(ak.stock_lhb_stock_detail_em, symbol=stock, date=date, flag="买入")
    return df


# ═══════════════════════════════════════════════════════════════
# 资金追踪
# ═══════════════════════════════════════════════════════════════

class MoneyFlow:
    """资金追踪 —— 主力/敢死队/多空/龙虎榜"""

    def __init__(self, top_n: int = 20):
        self.top_n = top_n

    def _normalize_rank(self, df: Optional[pd.DataFrame], indicator: str) -> List[Dict]:
        if df is None or df.empty:
            return []
        rename = {
            "代码": "code", "名称": "name", "最新价": "price",
            "今日涨跌幅": "pct_chg", "今日主力净流入-净额": "main_net",
            "今日主力净流入-净占比": "main_net_pct",
            "今日超大单净流入-净额": "xl_net",
            "今日大单净流入-净额": "big_net",
            "今日中单净流入-净额": "mid_net",
            "今日小单净流入-净额": "small_net",
        }
        prefix = {"今日": "今日", "3日": "3日", "5日": "5日", "10日": "10日"}.get(indicator, "今日")
        rename = {
            "代码": "code", "名称": "name", "最新价": "price",
            f"{prefix}涨跌幅": "pct_chg",
            f"{prefix}主力净流入-净额": "main_net",
            f"{prefix}主力净流入-净占比": "main_net_pct",
            f"{prefix}超大单净流入-净额": "xl_net",
            f"{prefix}大单净流入-净额": "big_net",
            f"{prefix}中单净流入-净额": "mid_net",
            f"{prefix}小单净流入-净额": "small_net",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        for col in ("main_net", "main_net_pct", "pct_chg"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["main_net"]).sort_values("main_net", ascending=False)
        rows = df.head(self.top_n).to_dict("records")
        for r in rows:
            r["indicator"] = indicator
        return rows

    # ---------------- 1. 主力资金 ----------------

    def get_main_flow(self, indicator: str = "今日") -> List[Dict]:
        """主力净流入排行；东财资金流接口失败时降级为龙虎榜净买榜"""
        df = fetch_fund_flow_rank(indicator)
        rows = self._normalize_rank(df, indicator)
        if rows:
            return rows
        # 降级：龙虎榜净买额榜（代表大资金真实动向）
        lhb = self.get_lhb(self.top_n)
        for r in lhb:
            r["indicator"] = f"{indicator}(龙虎榜降级)"
        return lhb

    def get_main_flow_overview(self) -> Dict:
        """今日/3日/5日 三榜"""
        return {
            "today": self.get_main_flow("今日"),
            "three_days": self.get_main_flow("3日"),
            "five_days": self.get_main_flow("5日"),
        }

    # ---------------- 2. 敢死队资金 ----------------

    def get_daredevil_flow(self, top_n: Optional[int] = None) -> List[Dict]:
        """敢死队资金：涨停/大涨 + 高换手 + 主力大幅净流入（游资接力特征）"""
        top_n = top_n or self.top_n
        df = fetch_fund_flow_rank("今日")
        if df is not None and not df.empty:
            rename = {
                "代码": "code", "名称": "name", "最新价": "price",
                "今日涨跌幅": "pct_chg",
                "今日主力净流入-净额": "main_net",
                "今日主力净流入-净占比": "main_net_pct",
                "今日超大单净流入-净额": "xl_net",
            }
            df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
            df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
            df["main_net"] = pd.to_numeric(df["main_net"], errors="coerce")
            df["main_net_pct"] = pd.to_numeric(df["main_net_pct"], errors="coerce")
            # 敢死队特征：涨幅>5%（接近涨停）+ 主力净占比高 + 净流入大
            dd = df[(df["pct_chg"] >= 5) & (df["main_net"] > 0)]
            dd = dd.sort_values("main_net_pct", ascending=False).head(top_n)
            rows = dd.to_dict("records")
            for r in rows:
                r["tag"] = "敢死队" if r.get("pct_chg", 0) >= 9.5 else "游资活跃"
            return rows

        # 降级：涨停池连板高标（封板资金大 = 游资敢死队特征）
        from analysis.theme_center import fetch_limit_up_pool
        zt = fetch_limit_up_pool()
        if zt is None or zt.empty:
            return []
        rename = {
            "代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "pct_chg",
            "封板资金": "seal_amount", "换手率": "turnover", "涨停统计": "limit_stats",
        }
        zt = zt.rename(columns={k: v for k, v in rename.items() if k in zt.columns})
        for col in ("seal_amount", "turnover"):
            if col in zt.columns:
                zt[col] = pd.to_numeric(zt[col], errors="coerce")
        if "seal_amount" in zt.columns:
            zt = zt.sort_values("seal_amount", ascending=False)
        rows = zt.head(top_n).to_dict("records")
        for r in rows:
            r["tag"] = "敢死队"
            r["source"] = "涨停池降级"
        return rows

    # ---------------- 3. 多空资金 ----------------

    def get_bull_bear(self) -> Dict:
        """多空对比：概念板块资金净流入汇总 + 个股主力统计（可用时）"""
        # 方法1：个股主力统计（东财，可能被风控）
        df = fetch_fund_flow_rank("今日")
        if df is not None and not df.empty:
            main_col = next((c for c in df.columns if "主力净流入-净额" in c and "今日" in c), None)
            if main_col is not None:
                net = pd.to_numeric(df[main_col], errors="coerce").dropna()
                bull = int((net > 0).sum())
                bear = int((net < 0).sum())
                total = bull + bear
                return {
                    "bull_count": bull,
                    "bear_count": bear,
                    "net_total": round(float(net.sum()) / 1e8, 2),  # 亿元
                    "ratio": round(bull / total, 3) if total else 0.5,
                    "direction": "多方占优" if bull > bear else ("空方占优" if bear > bull else "多空均衡"),
                    "source": "个股主力资金",
                }

        # 方法2：概念板块资金汇总（新浪，稳定）
        from analysis.theme_center import fetch_concept_boards
        boards = fetch_concept_boards()
        if boards is not None and not boards.empty:
            inflow_col = "流入资金"
            outflow_col = "流出资金"
            if inflow_col in boards.columns and outflow_col in boards.columns:
                # 新浪接口单位为亿元，直接汇总
                inflow = pd.to_numeric(boards[inflow_col], errors="coerce").sum()
                outflow = pd.to_numeric(boards[outflow_col], errors="coerce").sum()
                net_total = round(inflow - outflow, 2)
                bull = int((pd.to_numeric(boards[inflow_col], errors="coerce") > pd.to_numeric(boards[outflow_col], errors="coerce")).sum())
                bear = int(len(boards) - bull)
                return {
                    "bull_count": bull,
                    "bear_count": bear,
                    "net_total": net_total,
                    "ratio": round(bull / (bull + bear), 3) if (bull + bear) else 0.5,
                    "direction": "多方占优" if net_total > 0 else ("空方占优" if net_total < 0 else "多空均衡"),
                    "source": "概念板块资金汇总",
                }

        return {"bull_count": 0, "bear_count": 0, "net_total": 0, "ratio": 0.5,
                "direction": "数据不足", "source": "无数据"}

    # ---------------- 4. 龙虎榜 ----------------

    def get_lhb(self, top_n: Optional[int] = None) -> List[Dict]:
        """龙虎榜列表（近7日）"""
        top_n = top_n or self.top_n
        df = fetch_lhb_detail()
        if df is None or df.empty:
            return []
        rename = {
            "序号": "idx", "代码": "code", "名称": "name",
            "上榜日": "date", "解读": "note",
            "收盘价": "close", "涨跌幅": "pct_chg",
            "龙虎榜净买额": "net_buy", "龙虎榜买入额": "buy_amount",
            "龙虎榜卖出额": "sell_amount", "龙虎榜成交额": "amount",
            "市场总成交额": "market_amount", "净买额占总成交比": "net_ratio",
            "流通市值": "float_mv", "换手率": "turnover",
            "上榜原因": "reason",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        if "net_buy" in df.columns:
            df["net_buy"] = pd.to_numeric(df["net_buy"], errors="coerce")
            df = df.sort_values("net_buy", ascending=False)
        return df.head(top_n).to_dict("records")

    # ---------------- 汇总 ----------------

    def get_overview(self) -> Dict:
        return {
            "main_flow": self.get_main_flow_overview(),
            "daredevil": self.get_daredevil_flow(),
            "bull_bear": self.get_bull_bear(),
            "lhb": self.get_lhb(10),
            "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def get_money_flow_overview() -> Dict:
    """便捷函数"""
    return MoneyFlow().get_overview()
