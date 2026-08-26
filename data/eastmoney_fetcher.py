"""
东方财富 + 同花顺 混合数据源
==============================
直接调用东方财富和同花顺的公开HTTP API，无需 akshare 依赖。
比 baostock 更快、数据更全（实时行情、行业板块、北向资金等）。
"""
import os
import json
import time
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

from data.fetcher import DataFetcher
from data.models import (
    StockQuote, KLineData, FinancialData,
    CapitalFlowData, MarketSentimentData,
)
from utils.logger import logger

# 配置SSL证书（合并系统根证书，解决本机SSL拦截问题）
from utils.ssl_setup import setup_ssl
setup_ssl()


class EastMoneyFetcher(DataFetcher):
    """东方财富+同花顺混合数据源"""

    EASTMONEY_API = "https://push2.eastmoney.com/api/qt/clist/get"
    KLINE_API = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    # 东财历史K线接口熔断：一旦失败（风控/断连），本次进程内直接走腾讯降级，不再重试
    _push2his_blocked = False

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        })
        self._name_cache: Dict[str, str] = {}
        self._all_stocks_cache = None

    def _get(self, url, params=None, retries=3):
        """带重试的 GET 请求"""
        last_err = None
        for i in range(retries):
            try:
                r = self._session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                logger.debug(f"HTTP {r.status_code}: {url[:60]}")
            except Exception as e:
                last_err = e
                if i < retries - 1:
                    time.sleep(0.5 * (i + 1))
        if last_err:
            logger.debug(f"请求失败 {url[:60]}: {last_err}")
        return None

    # ======================== 实时行情 ========================

    def get_realtime_quote(self, codes: List[str]) -> Dict[str, StockQuote]:
        """获取实时行情（东方财富 ulist API）"""
        result = {}
        for batch in [codes[i:i+50] for i in range(0, len(codes), 50)]:
            # ulist.np/get 直接用 secids 逗号分隔，b: 格式已失效
            secids = ",".join([self._to_em_secid(c) for c in batch])
            data = self._get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                {
                    "fltt": "2",
                    "secids": secids,
                    "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f12,f14,f15,f16,f17,f18,f20,f21,f23",
                },
            )
            if not data or "data" not in data:
                continue
            items = self._diff_list(data["data"].get("diff")) or self._diff_list(data["data"].get("klines"))
            for item in items:
                code = item.get("f12", "")
                if not code:
                    continue
                try:
                    result[code] = StockQuote(
                        code=code,
                        name=item.get("f14", ""),
                        price=float(item.get("f2") or 0),
                        change_pct=float(item.get("f3") or 0),
                        change_amount=float(item.get("f4") or 0),
                        volume=float(item.get("f5") or 0),
                        amount=float(item.get("f6") or 0),
                        turnover=float(item.get("f8") or 0),
                        amplitude=float(item.get("f7") or 0),
                        high=float(item.get("f15") or 0),
                        low=float(item.get("f16") or 0),
                        open=float(item.get("f17") or 0),
                        pre_close=float(item.get("f18") or 0),
                        pe_dynamic=float(item.get("f9") or 0) if item.get("f9") and item["f9"] != "-" else None,
                        pb=float(item.get("f23") or 0) if item.get("f23") and item["f23"] != "-" else None,
                        total_market_cap=float(item.get("f20") or 0) if item.get("f20") and item["f20"] != "-" else None,
                        circulating_market_cap=float(item.get("f21") or 0) if item.get("f21") and item["f21"] != "-" else None,
                    )
                except (ValueError, TypeError) as e:
                    logger.debug(f"解析行情失败 {code}: {e}")
        return result

    @staticmethod
    def _to_em_secid(code: str) -> str:
        """转为东方财富 secid 格式"""
        if code.startswith("6") or code.startswith("5"):
            return f"1.{code}"
        return f"0.{code}"

    @staticmethod
    def _diff_list(diff):
        """东财 clist 接口的 diff 有时是 dict(键为索引) 有时是 list，统一转 list"""
        if isinstance(diff, dict):
            return list(diff.values())
        return diff or []

    # ======================== K线数据 ========================

    def get_history_kline(
        self, code: str, period: str = "daily",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> KLineData:
        """获取历史K线（东方财富）"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")

        # 周期映射
        klt_map = {"daily": 101, "weekly": 102, "monthly": 103}
        klt = klt_map.get(period, 101)
        # 复权映射
        fqt_map = {"": 0, "qfq": 1, "hfq": 2}
        fqt = fqt_map.get(adjust, 1)

        secid = self._to_em_secid(code)

        # 东财历史K线熔断：已被风控/断连时，直接走腾讯降级，避免每只股票浪费 3 次重试
        if EastMoneyFetcher._push2his_blocked:
            return self._get_kline_from_tencent(code, period, start_date, end_date, adjust)

        data = self._get(self.KLINE_API, {
            "secid": secid,
            "klt": klt, "fqt": fqt,
            "beg": start_date, "end": end_date,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "lmt": 500,
        }, retries=1)

        if not data or "data" not in data or not data["data"].get("klines"):
            # 东财历史K线接口被风控/断连时，熔断并降级到腾讯K线
            EastMoneyFetcher._push2his_blocked = True
            logger.info("🔌 东财历史K线接口熔断，后续直接走腾讯K线")
            return self._get_kline_from_tencent(code, period, start_date, end_date, adjust)

        rows = []
        for line in data["data"]["klines"]:
            parts = line.split(",")
            if len(parts) >= 10:
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]) / 100,  # 手
                    "amount": float(parts[6]),
                    "amplitude": float(parts[7]) if parts[7] != "-" else 0,
                    "change_pct": float(parts[8]) if parts[8] != "-" else 0,
                    "change": float(parts[9]) if parts[9] != "-" else 0,
                    "turnover": float(parts[10]) if len(parts) > 10 and parts[10] != "-" else 0,
                })

        df = pd.DataFrame(rows)
        df["volume"] = df["volume"].fillna(0)
        name = self.get_stock_name(code)
        return KLineData(code=code, name=name, df=df, period=period, adjust=adjust)

    def _get_kline_from_tencent(
        self, code: str, period: str, start_date: str, end_date: str, adjust: str
    ) -> KLineData:
        """腾讯K线降级源（东财 push2his 接口被风控/断连时使用）

        返回字段顺序: [date, open, close, high, low, volume(手)]
        """
        try:
            symbol = ("sh" if code.startswith(("6", "5")) else "sz") + code
            p_map = {"daily": "day", "weekly": "week", "monthly": "month"}
            p = p_map.get(period, "day")
            adj = {"": "", "qfq": "qfq", "hfq": "hfq"}.get(adjust, "qfq")
            beg = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if start_date else ""
            end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if end_date else ""

            url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={symbol},{p},{beg},{end},800,{adj}")
            r = self._session.get(url, headers={"Referer": "https://gu.qq.com/"}, timeout=self.timeout)
            node = r.json().get("data", {}).get(symbol, {})
            key = f"{adj}{p}" if adj else p  # qfqday / day / hfqday
            arr = node.get(key) or node.get(p) or []
            if not arr:
                return KLineData(code=code, period=period, adjust=adjust)

            rows = []
            for it in arr:
                if len(it) >= 6:
                    rows.append({
                        "date": it[0],
                        "open": float(it[1]),
                        "close": float(it[2]),
                        "high": float(it[3]),
                        "low": float(it[4]),
                        "volume": float(it[5]),  # 单位：手
                    })
            df = pd.DataFrame(rows)
            df["volume"] = df["volume"].fillna(0)
            return KLineData(code=code, name=self.get_stock_name(code), df=df, period=period, adjust=adjust)
        except Exception as e:
            logger.debug(f"腾讯K线降级失败 {code}: {e}")
            return KLineData(code=code, period=period, adjust=adjust)

    # ======================== 财务数据（同花顺） ========================

    def get_financial_data(self, code: str) -> FinancialData:
        """获取财务数据（使用东方财富 ulist API，逐只查询确保数据完整）"""
        name = self.get_stock_name(code)
        result = FinancialData(code=code, name=name)

        try:
            secid = self._to_em_secid(code)

            # 使用 ulist.np/get API（与 get_realtime_quote 相同端点，已验证可工作）
            data = self._get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                {
                    "fltt": "2",
                    "secids": secid,
                    "fields": (
                        "f2,f3,f9,f20,f21,f23,"
                        "f37,f38,f39,f40,f41,f42,f43,"
                        "f44,f45,f46,f47,f48,f49,f57,f58,f86,f115,f116"
                    ),
                },
            )

            if data and "data" in data:
                diff = data["data"].get("diff", [])
                if diff:
                    item = diff[0]
                    result.pe = self._f(item.get("f9"))
                    result.pb = self._f(item.get("f23"))
                    result.roe = self._f(item.get("f37"))
                    # 营收/利润增长率不在 ulist 快照接口中（f43/f45 实为营收额/净利润额，不是增长率），
                    # 需 datacenter 财务指标接口才能拿到，此处置 None 避免误报错误值
                    result.revenue_growth = None
                    result.profit_growth = None
                    result.gross_margin = self._f(item.get("f49"))
                    result.net_margin = self._f(item.get("f48"))
                    result.debt_ratio = self._f(item.get("f41"))
                    # f42 = 营业总收入，可用于规模因子
                    result.total_income = self._f(item.get("f42"))
                    result.total_market_cap = self._f(item.get("f20"))  # 总市值（f20，单位元）
                    result.dividend_yield = self._f(item.get("f86"))

                    logger.debug(
                        f"  财务数据 {code}: PE={result.pe} ROE={result.roe}"
                        f" 营收增长={result.revenue_growth} 利润增长={result.profit_growth}"
                    )

        except Exception as e:
            logger.debug(f"财务数据获取失败 {code}: {e}")

        return result

    # ======================== 市场情绪 ========================

    @staticmethod
    def _f(val) -> Optional[float]:
        """安全转float"""
        if val is None or val == "" or val == "-":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def get_market_sentiment(self) -> MarketSentimentData:
        """获取市场情绪（东方财富全市场统计）"""
        try:
            # 获取全市场涨跌统计
            data = self._get(self.EASTMONEY_API, {
                "pn": "1", "pz": "1",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f2,f3,f4,f12,f14",
            })
            # 获取涨停跌停数据
            up_data = self._get(self.EASTMONEY_API, {
                "pn": "1", "pz": "1",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f2,f104,f105,f106",
            })

            advance = decline = flat = limit_up = limit_down = 0
            # 粗略估算（每日涨跌约各半）
            total = 5000
            try:
                if data and "data" in data:
                    total = data["data"].get("total", 5000)
            except:
                pass

            # 简化的市场热度估算（真实涨跌家数暂未接入，此处为估算值）
            heat = 50  # 中性

            return MarketSentimentData(
                advance_count=advance or int(total * 0.48),
                decline_count=decline or int(total * 0.48),
                flat_count=flat or int(total * 0.04),
                limit_up_count=limit_up or 50,
                limit_down_count=limit_down or 10,
                market_heat_index=heat,
                source="东财·估算",
                estimated=True,
            )
        except Exception as e:
            logger.debug(f"市场情绪获取失败: {e}")
            return MarketSentimentData(source="获取失败", estimated=True)

    # ======================== 股票列表 ========================

    def get_index_components(self, index_code: str) -> List[str]:
        """获取指数成分股"""
        try:
            # 东方财富指数成分股
            fs_map = {
                "000300": "b:1+b:2",  # 沪深300
                "000905": "b:1+b:2+b:3",  # 中证500（近似）
                "000016": "b:1",  # 上证50（近似）
            }
            fs = fs_map.get(index_code, "b:1+b:2")
            data = self._get(self.EASTMONEY_API, {
                "pn": "1", "pz": "500",
                "fs": fs,
                "fields": "f12",
            })
            if data and "data" in data:
                items = self._diff_list(data["data"].get("diff"))
                return [item["f12"] for item in items if item.get("f12")]
        except Exception as e:
            logger.debug(f"获取指数成分股失败 {index_code}: {e}")
        return []

    def get_all_stocks_spot(self, max_pages: int = 20) -> pd.DataFrame:
        """获取全市场股票实时行情（分页，每页100只，按成交额降序）

        东财 clist 接口单页上限 100 只，需分页拉取；默认取成交额最大的前 2000 只，
        覆盖选股排名 popular(300)/all(2000) 池。
        """
        rows = []
        try:
            for pn in range(1, max_pages + 1):
                data = self._get(self.EASTMONEY_API, {
                    "pn": str(pn), "pz": "100",
                    "po": "0", "np": "1", "fltt": "2", "invid": "0",
                    "fid": "f6",  # 按成交额降序
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                    "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f12,f14,f15,f16,f17,f18,f20,f21,f23",
                })
                if not data or "data" not in data:
                    break
                items = self._diff_list(data["data"].get("diff"))
                if not items:
                    break
                for item in items:
                    name = item.get("f14", "")
                    price = float(item.get("f2") or 0)
                    # 过滤退市/停牌股（退市股名称含"退"，停牌价<=0）
                    if "退" in name or price <= 0:
                        continue
                    rows.append({
                        "code": item.get("f12", ""),
                        "name": name,
                        "price": price,
                        "change_pct": float(item.get("f3") or 0),
                        "volume": float(item.get("f5") or 0),
                        "amount": float(item.get("f6") or 0),
                        "pe": float(item.get("f9") or 0) if item.get("f9") and item["f9"] != "-" else None,
                        "pb": float(item.get("f23") or 0) if item.get("f23") and item["f23"] != "-" else None,
                        "total_market_cap": float(item.get("f20") or 0) if item.get("f20") and item["f20"] != "-" else None,
                    })
                if len(items) < 100:
                    break  # 最后一页
        except Exception as e:
            logger.debug(f"全市场行情获取失败: {e}")
        return pd.DataFrame(rows)

    def get_top_n_by_market_cap(self, n: int = 500) -> List[Dict[str, object]]:
        """
        获取沪深A股市值排名前N只股票

        使用东方财富 clist API，按总市值(f20)降序排列。

        Args:
            n: 返回前N只（默认500）

        Returns:
            [{'code': '600519', 'name': '贵州茅台', 'total_market_cap': 20000000000}, ...]
        """
        try:
            # 沪深A股 filter: m:0+t:6(主板), m:0+t:80(科创板), m:1+t:2(中小板), m:1+t:23(创业板)
            # 排除北交所
            data = self._get(self.EASTMONEY_API, {
                "pn": "1", "pz": str(min(n, 5000)),
                "po": "0",           # 0=降序
                "np": "1",
                "fltt": "2",
                "invid": "0",
                "fid": "f20",        # 按总市值排序
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f14,f20",
            })
            if data and "data" in data:
                items = self._diff_list(data["data"].get("diff"))
                results = []
                for item in items[:n]:
                    cap = self._f(item.get("f20"))
                    if cap is not None:
                        results.append({
                            "code": item.get("f12", ""),
                            "name": item.get("f14", ""),
                            "total_market_cap": cap,
                        })
                logger.info(f"市值排名前{n}: 获取到 {len(results)}只")
                return results
        except Exception as e:
            logger.error(f"获取市值排名失败: {e}")
        return []

    def get_stock_name(self, code: str) -> str:
        """获取股票名称"""
        if code in self._name_cache:
            return self._name_cache[code]

        try:
            secid = self._to_em_secid(code)
            # ulist.np/get 单只查询
            data = self._get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                {"fltt": "2", "secids": secid, "fields": "f12,f14"},
                retries=2,
            )
            if data and "data" in data:
                diff = self._diff_list(data["data"].get("diff"))
                if diff:
                    name = diff[0].get("f14", "") or code
                    self._name_cache[code] = name
                    return name
        except Exception as e:
            logger.debug(f"获取股票名称失败 {code}: {e}")
        return code

    def search_stocks(self, keyword: str) -> List[Dict[str, str]]:
        """搜索股票"""
        try:
            # 用东方财富搜索
            data = self._get("https://searchadapter.eastmoney.com/api/suggest/get", {
                "input": keyword, "type": "14", "token": "D43BF722C8E33BDC906FB84D85E326E8",
                "count": "20",
            })
            if data and "QuotationCodeTable" in data:
                items = data["QuotationCodeTable"].get("Data", [])
                results = []
                for item in items:
                    code = item.get("Code", "")
                    if len(code) == 6 and code.isdigit():
                        results.append({
                            "code": code,
                            "name": item.get("Name", ""),
                            "sector": item.get("MktNum", ""),
                        })
                return results[:20]
        except:
            pass

        # 回退：本地搜索
        if self._all_stocks_cache is None:
            try:
                df = self.get_all_stocks_spot()
                self._all_stocks_cache = df
            except:
                self._all_stocks_cache = pd.DataFrame()

        if not self._all_stocks_cache.empty:
            kw = keyword.lower()
            mask = self._all_stocks_cache["code"].str.contains(kw, na=False) | \
                   self._all_stocks_cache["name"].str.contains(kw, na=False)
            matched = self._all_stocks_cache[mask].head(20)
            return [{"code": r["code"], "name": r["name"], "sector": ""}
                    for _, r in matched.iterrows()]

        return []

    def batch_get_financial_data(self, codes: List[str]) -> Dict[str, FinancialData]:
        """批量获取财务数据（一次API调用查多只股票）"""
        result = {}
        if not codes:
            return result

        # 先获取名称缓存
        for code in codes:
            result[code] = FinancialData(code=code, name=self.get_stock_name(code))

        # 批量查询，每次最多100只（URL长度限制）
        fields = "f12,f14,f2,f9,f20,f21,f23,f37,f38,f39,f40,f41,f42,f43,f44,f45,f46,f47,f48,f49,f57,f58,f86,f115,f116"
        batch_size = 100
        for batch_start in range(0, len(codes), batch_size):
            batch = codes[batch_start:batch_start + batch_size]
            secids = ",".join([self._to_em_secid(c) for c in batch])
            data = self._get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                {
                    "fltt": "2",
                    "secids": secids,
                    "fields": fields,
                },
            )
            if data and "data" in data:
                items = self._diff_list(data["data"].get("diff"))
                for item in items:
                    code = item.get("f12", "")
                    if code not in result:
                        continue
                    self._name_cache[code] = code
                    fin = result[code]
                    fin.pe = self._f(item.get("f9"))
                    fin.pb = self._f(item.get("f23"))
                    fin.roe = self._f(item.get("f37"))
                    # 营收/利润增长率不在 ulist 快照接口中（f43/f45 是营收额/净利润额），置 None 避免误报
                    fin.revenue_growth = None
                    fin.profit_growth = None
                    fin.gross_margin = self._f(item.get("f49"))
                    fin.net_margin = self._f(item.get("f48"))
                    fin.debt_ratio = self._f(item.get("f41"))
                    fin.total_income = self._f(item.get("f42"))
                    fin.total_market_cap = self._f(item.get("f20"))  # 总市值（f20，单位元）
                    fin.dividend_yield = self._f(item.get("f86"))
                    # 从原始数据中提取名称
                    name = item.get("f14", "")
                    if name:
                        self._name_cache[code] = name
                        fin.name = name
            if batch_start + batch_size < len(codes):
                time.sleep(0.3)  # 防止频率过高

        logger.info(f"批量财务数据: {len(codes)}只 → {sum(1 for v in result.values() if v.pe is not None)}只有效")
        return result

    def batch_get_history_kline(self, codes: List[str], days: int = 120) -> Dict[str, pd.DataFrame]:
        """
        批量获取K线数据（并行加速版）

        使用线程池并行获取，大幅提升500只股票的获取速度。
        前10只热身 → 之后并发10线程。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=int(days * 1.6))).strftime("%Y%m%d")
        kline_data: Dict[str, pd.DataFrame] = {}
        success_count = 0
        total = len(codes)

        logger.info(f"并行K线获取: {total}只 (线程池10)")

        def _get_one(code: str):
            try:
                kline = self.get_history_kline(
                    code, period="daily",
                    start_date=start_date, end_date=end_date,
                    adjust="qfq",
                )
                if kline is not None and not kline.df.empty and len(kline.df) >= 21:
                    return code, kline.df
            except Exception:
                pass
            return code, None

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_get_one, c): c for c in codes}
            for fut in as_completed(futures):
                code, df = fut.result()
                if df is not None:
                    kline_data[code] = df
                    success_count += 1
                # 每50只打一次日志
                done = len(kline_data) + (total - len(futures))
                if (success_count + (total - len(futures))) % 50 == 0 or \
                   (success_count + (total - len(futures))) == total:
                    pass  # 日志在循环外统一打

        logger.info(f"  K线批获取: {success_count}/{total} 成功")
        return kline_data

    def get_all_stocks_with_financial(self) -> pd.DataFrame:
        """获取全市场股票的行情+基础财务数据（1-2次API调用）"""
        # 先获取全市场行情（含PE/PB/市值）
        df = self.get_all_stocks_spot()
        if df.empty:
            return df
        # 补充更多财务字段（ROE、营收增长等）— 用批量接口
        codes = df["code"].tolist()
        fin_map = self.batch_get_financial_data(codes)
        rows = []
        for _, row in df.iterrows():
            code = row["code"]
            fin = fin_map.get(code)
            if fin:
                row["roe"] = fin.roe
                row["revenue_growth"] = fin.revenue_growth
                row["profit_growth"] = fin.profit_growth
                row["gross_margin"] = fin.gross_margin
                row["debt_ratio"] = fin.debt_ratio
            rows.append(row)
        return pd.DataFrame(rows)

    def get_capital_flow(self, code: str) -> CapitalFlowData:
        """获取个股资金流向（东财 ulist 接口，金额单位元 → 转万元）"""
        result = CapitalFlowData(code=code, name=self.get_stock_name(code))
        try:
            secid = self._to_em_secid(code)
            data = self._get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                {
                    "fltt": "2",
                    "secids": secid,
                    "fields": "f62,f66,f72,f78,f84,f184",
                },
            )
            if data and "data" in data:
                diff = self._diff_list(data["data"].get("diff"))
                if diff:
                    item = diff[0]

                    def _w(v):
                        x = self._f(v)
                        return round(x / 1e4, 2) if x is not None else None

                    result.main_net_inflow = _w(item.get("f62"))       # 主力净流入
                    result.super_large_net_inflow = _w(item.get("f66"))  # 超大单
                    result.large_net_inflow = _w(item.get("f72"))      # 大单
                    result.medium_net_inflow = _w(item.get("f78"))     # 中单
                    result.small_net_inflow = _w(item.get("f84"))      # 小单
                    result.main_inflow_ratio = self._f(item.get("f184"))  # 主力净占比(%)
        except Exception as e:
            logger.debug(f"资金流向获取失败 {code}: {e}")
        return result


# 数据源注册
try:
    from data.fetcher import DataFetcherFactory
    DataFetcherFactory.register("eastmoney", EastMoneyFetcher)
except:
    pass
