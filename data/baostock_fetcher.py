"""
Baostock数据源实现
==================
基于 baostock 库。核心优化：PE/PB从K线数据提取缓存，减少额外查询。
"""
import time
import socket
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
import numpy as np
import baostock as bs

from data.fetcher import DataFetcher
from data.models import StockQuote, KLineData, FinancialData, CapitalFlowData, MarketSentimentData
from utils.logger import logger


class BaostockFetcher(DataFetcher):

    def __init__(self, timeout: int = 6, max_retries: int = 1, retry_delay: float = 0.2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._name_cache: Dict[str, str] = {}
        self._logged_in = False
        # PE/PB来自K线缓存
        self._pe_pb_cache: Dict[str, dict] = {}

    def _ensure_login(self):
        if not self._logged_in:
            old = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self.timeout)
            try:
                lg = bs.login()
                if lg.error_code != '0':
                    raise ConnectionError(f"baostock登录失败: {lg.error_msg}")
                self._logged_in = True
            finally:
                socket.setdefaulttimeout(old)

    @staticmethod
    def _to_bs_code(code: str) -> str:
        code = code.strip()
        return f"sh.{code}" if code.startswith(("6", "5")) else f"sz.{code}"

    @staticmethod
    def _from_bs_code(bs_code: str) -> str:
        return bs_code.replace("sh.", "").replace("sz.", "")

    @staticmethod
    def _to_float(val, default=0.0):
        try:
            return float(val) if val not in (None, "", "-") else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _to_optional_float(val):
        try:
            if val not in (None, "", "-"):
                f = float(val)
                return f if not np.isnan(f) else None
            return None
        except (ValueError, TypeError):
            return None

    # ======================== K线数据 ========================

    def get_history_kline(self, code: str, period="daily",
                          start_date=None, end_date=None, adjust="qfq",
                          is_index: bool = False) -> KLineData:
        """获取K线，peTTM/pbMRQ字段自动缓存供财务分析
        is_index=True: 指数代码显式 sh./sz. 前缀(000300→sh.000300, 399→sz.)，
        否则会被当深市个股。period: daily/weekly/monthly
        """
        self._ensure_login()

        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if end_date else datetime.now().strftime("%Y-%m-%d")
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if start_date else (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")

        adjust_map = {"": "1", "qfq": "2", "hfq": "3"}
        freq_map = {"daily": "d", "weekly": "w", "monthly": "m"}
        frequency = freq_map.get(period, "d")
        if is_index:
            bs_code = ("sh." if not code.startswith("399") else "sz.") + code
        else:
            bs_code = self._to_bs_code(code)
        fields = "date,open,close,high,low,volume,amount,turn,pctChg,peTTM,pbMRQ"

        try:
            old = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self.timeout)
            rs = bs.query_history_k_data_plus(bs_code, fields, start_date=start, end_date=end,
                                              frequency=frequency, adjustflag=adjust_map.get(adjust, "2"))
            socket.setdefaulttimeout(old)
            if not rs or rs.error_code != '0':
                return KLineData(code=code, period=period, adjust=adjust)

            data = []
            while rs.next():
                data.append(rs.get_row_data())
            if not data:
                return KLineData(code=code, period=period, adjust=adjust)

            df = pd.DataFrame(data, columns=["date","open","close","high","low","volume","amount","turnover","change_pct","pe","pb"])
            for col in ["open","close","high","low","volume","amount","turnover","change_pct"]:
                df[col] = df[col].apply(self._to_float)
            df["volume"] = df["volume"] / 100

            # 缓存PE/PB（个股才有意义，指数无 PE/PB 字段）
            if not is_index:
                last = data[-1]
                pe = self._to_optional_float(last[9])
                pb = self._to_optional_float(last[10])
                if pe or pb:
                    self._pe_pb_cache[code] = {"pe": pe, "pb": pb}

            name = code if is_index else self.get_stock_name(code)
            return KLineData(code=code, name=name, df=df, period=period, adjust=adjust)
        except Exception:
            return KLineData(code=code, period=period, adjust=adjust)

    # ======================== 财务数据（极简版） ========================

    def get_financial_data(self, code: str) -> FinancialData:
        """快速财务数据 — 只取PE/PB（K线缓存），其他用默认值"""
        result = FinancialData(code=code, name=self.get_stock_name(code))

        # 从K线缓存拿PE/PB
        cached = self._pe_pb_cache.get(code, {})
        result.pe = cached.get("pe")
        result.pb = cached.get("pb")

        # 如果缓存没有，快速查一次
        if not result.pe:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                old = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.timeout)
                rs = bs.query_history_k_data_plus(self._to_bs_code(code), "date,peTTM,pbMRQ",
                                                   start_date=today, end_date=today,
                                                   frequency="d", adjustflag="2")
                socket.setdefaulttimeout(old)
                if rs and rs.error_code == '0':
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        result.pe = self._to_optional_float(rows[-1][1])
                        result.pb = self._to_optional_float(rows[-1][2])
            except Exception:
                pass

        # 不设置默认值——缺失就保持None，让下游恰当处理
        return result

    # ======================== 市场情绪 ========================

    def get_market_sentiment(self) -> MarketSentimentData:
        self._ensure_login()
        result = MarketSentimentData(source="baostock·估算", estimated=True)
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            old = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self.timeout)
            rs = bs.query_history_k_data_plus("sh.000001", "date,pctChg",
                                               start_date=today, end_date=today,
                                               frequency="d", adjustflag="2")
            socket.setdefaulttimeout(old)
            if rs and rs.error_code == '0':
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    pct = self._to_float(rows[-1][1])
                    if pct > 1:
                        result.advance_count, result.decline_count = 2500, 1500
                        result.market_heat_index = 60
                    elif pct > 0:
                        result.advance_count, result.decline_count = 2200, 1800
                        result.market_heat_index = 52
                    elif pct > -1:
                        result.advance_count, result.decline_count = 1800, 2200
                        result.market_heat_index = 48
                    else:
                        result.advance_count, result.decline_count = 1200, 2800
                        result.market_heat_index = 35
        except Exception:
            result.market_heat_index = 50
        return result

    # ======================== 股票池 ========================

    def get_top_n_by_market_cap(self, n: int = 500) -> List[Dict]:
        """通过baostock获取全市场股票"""
        self._ensure_login()
        today = datetime.now().strftime("%Y-%m-%d")
        for day in [today, (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                     (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")]:
            try:
                old = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.timeout)
                rs = bs.query_all_stock(day)
                socket.setdefaulttimeout(old)
                if rs and rs.error_code == '0':
                    stocks = []
                    while rs.next():
                        row = rs.get_row_data()
                        if row and len(row) >= 2:
                            c = self._from_bs_code(row[0])
                            if c.startswith(("0", "3", "6")) and c.isdigit():
                                stocks.append({"code": c, "name": row[1]})
                    if stocks:
                        return stocks[:n]
            except Exception:
                continue
        return []

    def get_index_components(self, index_code: str) -> List[str]:
        """获取指数成分股"""
        try:
            self._ensure_login()
            queries = {"000300": bs.query_hs300_stocks, "hs300": bs.query_hs300_stocks,
                       "000905": bs.query_zz500_stocks, "zz500": bs.query_zz500_stocks,
                       "000016": bs.query_sz50_stocks, "sz50": bs.query_sz50_stocks}
            if index_code in queries:
                old = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.timeout * 2)
                rs = queries[index_code]()
                socket.setdefaulttimeout(old)
                if rs and rs.error_code == '0':
                    codes = []
                    while rs.next():
                        row = rs.get_row_data()
                        if row and len(row) >= 2 and row[1]:
                            codes.append(self._from_bs_code(row[1]))
                    if codes:
                        return codes
        except Exception:
            pass
        return []

    # ======================== 其他 ========================

    def get_realtime_quote(self, codes: List[str]) -> Dict[str, StockQuote]:
        self._ensure_login()
        result = {}
        today = datetime.now().strftime("%Y-%m-%d")
        for code in codes:
            try:
                old = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.timeout)
                rs = bs.query_history_k_data_plus(self._to_bs_code(code),
                    "date,open,close,high,low,volume,amount,turn,pctChg,peTTM,pbMRQ",
                    start_date=today, end_date=today, frequency="d", adjustflag="2")
                socket.setdefaulttimeout(old)
                if not rs or rs.error_code != '0':
                    continue
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    r = rows[-1]
                    result[code] = StockQuote(code=code, name=self.get_stock_name(code),
                        price=self._to_float(r[2]), change_pct=self._to_float(r[8]),
                        volume=self._to_float(r[5]), amount=self._to_float(r[6]),
                        turnover=self._to_float(r[7]), high=self._to_float(r[3]),
                        low=self._to_float(r[4]), open=self._to_float(r[1]),
                        pre_close=self._to_float(r[2]) - self._to_float(r[2]) * self._to_float(r[8]) / 100,
                        pe_dynamic=self._to_optional_float(r[9]), pb=self._to_optional_float(r[10]))
            except Exception:
                pass
        return result

    def get_capital_flow(self, code: str) -> CapitalFlowData:
        return CapitalFlowData(code=code, name=self.get_stock_name(code))

    def get_all_stocks_spot(self) -> pd.DataFrame:
        """获取全市场股票行情（通过 baostock query_all_stock + history_k_data）"""
        self._ensure_login()
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            rs = bs.query_all_stock(today)
            if not rs or rs.error_code != '0':
                # 尝试前一天
                rs = bs.query_all_stock(
                    (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                )
            if rs and rs.error_code == '0':
                stocks = []
                while rs.next():
                    row = rs.get_row_data()
                    if row and len(row) >= 2:
                        c = self._from_bs_code(row[0])
                        if c.startswith(("0", "3", "6")) and c.isdigit():
                            stocks.append({
                                "code": c,
                                "name": row[1],
                                "price": 0.0,
                                "amount": 0.0,
                                "pe": None,
                                "pb": None,
                            })
                if stocks:
                    df = pd.DataFrame(stocks)
                    # baostock 无实时价格/市值，以下为占位值（避免被过滤），
                    # 用 estimated 标记提醒下游这是估算数据
                    df["price"] = 1.0
                    df["amount"] = 0.0
                    df["pe"] = None
                    df["pb"] = None
                    df["total_market_cap"] = 0.0
                    df["estimated"] = True
                    return df
        except Exception as e:
            logger.debug(f"获取全市场行情失败: {e}")
        return pd.DataFrame()

    def get_stock_name(self, code: str) -> str:
        if code in self._name_cache:
            return self._name_cache[code]
        self._ensure_login()
        try:
            rs = bs.query_stock_basic(code=self._to_bs_code(code))
            if rs and rs.error_code == '0':
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows and len(rows[0]) > 1:
                    self._name_cache[code] = rows[0][1]
                    return rows[0][1]
        except Exception:
            pass
        return code

    def search_stocks(self, keyword: str) -> List[Dict[str, str]]:
        self._ensure_login()
        results = []
        try:
            rs = bs.query_stock_basic(code_name=keyword)
            while rs and rs.next():
                row = rs.get_row_data()
                if len(row) >= 2:
                    results.append({"code": self._from_bs_code(row[0]), "name": row[1]})
        except Exception:
            pass
        return results[:20]

    def __del__(self):
        try:
            if self._logged_in:
                bs.logout()
        except Exception:
            pass
