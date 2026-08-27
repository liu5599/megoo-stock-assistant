"""
题材中心（挖热点）— 对标「容维题材宝典」
=====================================
核心能力：
  1. 新题材挖得快：概念板块涨幅榜 + 主力净流入榜（每日新晋热点）
  2. 热题材挖得深：涨停家数统计 + 板块内领涨股 + 连板高度
  3. 情绪个股挖得精：涨停池标记（首板/连板/炸板），识别情绪龙头

数据源：东方财富概念板块 + 涨停板池（akshare）
"""
import time
from typing import Dict, List, Optional

import pandas as pd


# 概念名 → 行业名 映射表（题材降级匹配用，解决"概念vs行业"错配）
CONCEPT_INDUSTRY_MAP = {
    "转基因": ["种植业", "农化制品", "农产品加工", "食品加工"],
    "粮食": ["种植业", "农产品加工", "食品加工", "农化制品"],
    "农业": ["种植业", "农化制品", "农产品加工", "饲料", "养殖业"],
    "AI": ["半导体", "计算机设", "通信设备", "元件", "软件开发", "游戏"],
    "人工智能": ["半导体", "计算机设", "通信设备", "元件", "软件开发"],
    "算力": ["半导体", "计算机设", "通信设备", "元件"],
    "芯片": ["半导体", "元件", "电子化学"],
    "半导体": ["半导体", "元件", "电子化学"],
    "军工": ["国防军工", "航空装备", "航天装备", "地面兵装"],
    "医药": ["化学制药", "生物制品", "医疗器械", "医疗服务", "中药"],
    "券商": ["证券Ⅱ", "证券", "多元金融"],
    "黄金": ["贵金属", "饰品"],
    "有色": ["贵金属", "小金属", "工业金属", "能源金属"],
    "新能源": ["光伏设备", "电池", "电网设备", "风电设备"],
    "光伏": ["光伏设备", "电池"],
    "锂电": ["电池", "能源金属", "小金属"],
    "汽车": ["汽车零部", "汽车整车", "乘用车", "商用车"],
    "地产": ["房地产开", "房地产开发"],
    "消费": ["食品加工", "饮料乳品", "白酒", "零售", "饰品"],
    "白酒": ["白酒", "食品加工"],
    "机器人": ["自动化设备", "通用设备", "专用设备"],
    "低空": ["航空装备", "航天装备", "军工电子"],
    "航天": ["航天装备", "军工电子"],
    "电力": ["电力", "电网设备", "绿电"],
}


def _match_industries(board_name: str, zt: pd.DataFrame) -> pd.DataFrame:
    """概念名 → 涨停池行业匹配（直接包含 + 映射表补充）"""
    if "所属行业" not in zt.columns:
        return zt.iloc[0:0]
    mask = zt["所属行业"].astype(str).str.contains(board_name, na=False)
    for keyword, industries in CONCEPT_INDUSTRY_MAP.items():
        if keyword in board_name:
            for ind in industries:
                mask = mask | zt["所属行业"].astype(str).str.contains(ind, na=False)
    return zt[mask]

from utils.logger import logger
from analysis._cache import ttl_cache


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


# 东财概念板块熔断（新浪主源失败时才触发东财降级，失败一次后不再重试）
_eastmoney_board_blocked = False


@ttl_cache(300)
def fetch_concept_boards() -> Optional[pd.DataFrame]:
    """概念板块行情（主源：新浪概念资金流，缓存5分钟）"""
    global _eastmoney_board_blocked
    ak = __import__("akshare", fromlist=["stock_fund_flow_concept"])
    df = _safe_call(ak.stock_fund_flow_concept, "即时")
    if df is None or df.empty:
        # 降级：东财概念板块（熔断保护）
        if not _eastmoney_board_blocked:
            ak = __import__("akshare", fromlist=["stock_board_concept_name_em"])
            df = _safe_call(ak.stock_board_concept_name_em)
            if df is None:
                _eastmoney_board_blocked = True
    return df


@ttl_cache(300)
def fetch_limit_up_pool(date: str = "") -> Optional[pd.DataFrame]:
    """涨停板池（当日/指定日期，缓存5分钟）；Tushare(付费兜底) → 东财"""
    if not date:
        date = pd.Timestamp.now().strftime("%Y%m%d")

    # 1. Tushare 优先（收盘后有精确涨跌停列表）
    try:
        from data.tushare_fetcher import tushare_enabled, fetch_limit_list
        if tushare_enabled():
            df = fetch_limit_list(date, "U")
            if df is not None and not df.empty:
                # 兼容东财涨停池字段
                df["代码"] = df["code"].str[-6:]
                df["名称"] = df.get("名称", "")
                df["涨跌幅"] = df.get("pct_chg", 10.0)
                df["连板数"] = df.get("limit_times", 1)
                df["所属行业"] = df.get("industry", "")
                df["封板资金"] = df.get("fund", 0)
                return df[["代码", "名称", "涨跌幅", "连板数", "所属行业", "封板资金"]]
    except Exception as e:
        logger.warning(f"Tushare涨停池失败: {e}")

    # 2. 东财
    ak = __import__("akshare", fromlist=["stock_zt_pool_em"])
    df = _safe_call(ak.stock_zt_pool_em, date=date)
    return df


def fetch_limit_down_pool(date: str = "") -> Optional[pd.DataFrame]:
    """跌停板池"""
    if not date:
        date = pd.Timestamp.now().strftime("%Y%m%d")
    ak = __import__("akshare", fromlist=["stock_zt_pool_dtgc_em"])
    df = _safe_call(ak.stock_zt_pool_dtgc_em, date=date)
    return df


def fetch_board_cons(symbol: str) -> Optional[pd.DataFrame]:
    """概念板块成分股"""
    ak = __import__("akshare", fromlist=["stock_board_concept_cons_em"])
    df = _safe_call(ak.stock_board_concept_cons_em, symbol=symbol)
    return df


# ═══════════════════════════════════════════════════════════════
# 题材中心
# ═══════════════════════════════════════════════════════════════

class ThemeCenter:
    """题材中心 —— 新题材挖得快 + 热题材挖得深 + 情绪个股挖得精"""

    def __init__(self, top_n: int = 15):
        self.top_n = top_n

    # ---------------- 1. 新题材挖得快 ----------------

    def get_new_themes(self, top_n: Optional[int] = None) -> List[Dict]:
        """概念板块涨幅榜（新晋热点）"""
        top_n = top_n or self.top_n
        df = fetch_concept_boards()
        if df is None or df.empty:
            return []
        # 兼容列名（新浪资金流 / 东财概念板块两种结构）
        rename = {
            "行业": "name", "板块名称": "name",
            "行业指数": "index_price", "最新价": "price",
            "行业-涨跌幅": "pct_chg", "涨跌幅": "pct_chg",
            "流入资金": "inflow", "流出资金": "outflow",
            "净额": "net_flow",
            "公司家数": "stock_count", "上涨家数": "up_count", "下跌家数": "down_count",
            "领涨股": "leader", "领涨股-涨跌幅": "leader_pct",
            "总市值": "total_mv", "换手率": "turnover",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        for col in ("pct_chg", "net_flow", "inflow", "outflow"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "pct_chg" in df.columns:
            df = df.sort_values("pct_chg", ascending=False)
        rows = df.head(top_n).to_dict("records")
        for r in rows:
            if "net_flow" in r and r.get("net_flow") is not None and not pd.isna(r.get("net_flow")):
                try:
                    r["net_flow_yi"] = round(float(r["net_flow"]) / 1e8, 2)  # 万元→亿
                except Exception:
                    r["net_flow_yi"] = None
        return rows

    # ---------------- 2. 热题材挖得深 ----------------

    def get_hot_themes(self, top_n: Optional[int] = None) -> List[Dict]:
        """热度综合榜：涨幅 + 涨停家数 + 领涨股
        概念行情可用时用资金流数据；不可用时降级为涨停池行业分布（稳定源）。
        """
        top_n = top_n or self.top_n
        boards = self.get_new_themes(top_n=60)
        zt = fetch_limit_up_pool()
        zt_board_counter = {}
        if zt is not None and not zt.empty:
            if "所属行业" in zt.columns:
                for b in zt["所属行业"].dropna():
                    zt_board_counter[b] = zt_board_counter.get(b, 0) + 1
            if "涨停统计" in zt.columns:
                pass  # 东财涨停池无板块列时跳过

        # 概念行情可用 → 正常热度计算
        if boards:
            for item in boards:
                item["limit_up_count"] = zt_board_counter.get(item.get("name", ""), 0)

            # 综合热度分 = 涨幅*0.5 + 涨停家数*5（每家5分，上限50）
            def _heat(x):
                return x.get("pct_chg", 0) * 0.5 + min(x.get("limit_up_count", 0) * 5, 50)

            for item in boards:
                item["heat_score"] = round(_heat(item), 1)

            boards.sort(key=lambda x: x.get("heat_score", 0), reverse=True)
            return boards[:top_n]

        # 降级：涨停池行业分布 = 题材热度（容维核心逻辑：涨停集中度 = 热点主线）
        if zt_board_counter:
            fallback = []
            for b, cnt in sorted(zt_board_counter.items(), key=lambda x: -x[1]):
                fallback.append({
                    "name": b,
                    "pct_chg": None,
                    "leader": None,
                    "limit_up_count": cnt,
                    "heat_score": round(min(cnt * 5, 50), 1),
                    "source": "涨停池降级",
                })
            return fallback[:top_n]

        return []

    def get_theme_detail(self, board_name: str) -> Dict:
        """单个题材深度：成分股涨幅榜 → 龙头识别
        主源：东财概念成分；限频时降级为涨停池同行业股票。
        """
        df = fetch_board_cons(board_name)
        if df is None or df.empty:
            # 降级：涨停池中该行业股票（稳定源）
            zt = fetch_limit_up_pool()
            fallback = []
            if zt is not None and not zt.empty and "所属行业" in zt.columns:
                pool = _match_industries(board_name, zt)
                for _, r in pool.iterrows():
                    fallback.append({
                        "code": r.get("代码", ""),
                        "name": r.get("名称", ""),
                        "price": r.get("最新价"),
                        "pct_chg": r.get("涨跌幅"),
                        "turnover": None,
                        "pe": None,
                        "total_mv": None,
                        "seal_amount": r.get("封板资金"),
                        "boards": r.get("连板数"),
                    })
            if fallback:
                return {"name": board_name, "stocks": fallback,
                        "leader": fallback[0] if fallback else None, "source": "涨停池降级"}
            return {"name": board_name, "stocks": [], "leader": None}
        rename = {
            "代码": "code", "名称": "name", "最新价": "price",
            "涨跌幅": "pct_chg", "换手率": "turnover", "市盈率-动态": "pe",
            "总市值": "total_mv",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        df = df.sort_values("pct_chg", ascending=False)
        stocks = df.head(20).to_dict("records")
        leader = stocks[0] if stocks else None
        return {"name": board_name, "stocks": stocks, "leader": leader}

    # ---------------- 3. 情绪个股挖得精 ----------------

    def get_sentiment_stocks(self, top_n: int = 20) -> List[Dict]:
        """情绪个股：涨停池中标记首板/连板/炸板，识别情绪龙头"""
        zt = fetch_limit_up_pool()
        if zt is None or zt.empty:
            return []
        rename = {
            "代码": "code", "名称": "name", "涨跌幅": "pct_chg",
            "最新价": "price", "成交额": "amount", "流通市值": "float_mv",
            "总市值": "total_mv", "换手率": "turnover", "封板资金": "seal_amount",
            "首次封板时间": "first_seal_time", "最后封板时间": "last_seal_time",
            "炸板次数": "break_times", "涨停统计": "limit_stats",
            "连板数": "consecutive_days", "所属行业": "industry",
        }
        zt = zt.rename(columns={k: v for k, v in rename.items() if k in zt.columns})

        # 标记类型
        def _tag(row):
            days = row.get("consecutive_days")
            try:
                days = int(days)
            except Exception:
                days = 1
            if days >= 3:
                return "高标龙头"
            elif days == 2:
                return "二连板"
            else:
                return "首板"

        rows = []
        for _, r in zt.iterrows():
            d = r.to_dict()
            d["tag"] = _tag(r)
            rows.append(d)

        # 高标龙头优先，其次封板资金大的
        rank_map = {"高标龙头": 0, "二连板": 1, "首板": 2}
        rows.sort(key=lambda x: (rank_map.get(x.get("tag"), 3),
                                 -float(x.get("seal_amount") or 0)))
        return rows[:top_n]

    # ---------------- 汇总 ----------------

    def get_overview(self) -> Dict:
        """题材中心总览（供面板/日报）"""
        return {
            "new_themes": self.get_new_themes(self.top_n),
            "hot_themes": self.get_hot_themes(self.top_n),
            "sentiment_stocks": self.get_sentiment_stocks(),
            "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def get_theme_overview() -> Dict:
    """便捷函数"""
    return ThemeCenter().get_overview()
