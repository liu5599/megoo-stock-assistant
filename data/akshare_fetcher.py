"""
Akshare数据源实现
================
基于 akshare 库实现 DataFetcher 接口，提供沪深A股数据获取能力。
支持：实时行情、历史K线、财务数据、资金流向、市场情绪等。

Akshare API参考：
- 实时行情: stock_zh_a_spot_em
- 历史K线: stock_zh_a_hist
- 财务数据: stock_financial_abstract
- 资金流向: stock_individual_fund_flow
- 市场情绪: stock_market_activity_legu
- 北向资金: stock_hsgt_hist_em
"""

import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
import akshare as ak

from data.fetcher import DataFetcher
from data.models import (
    StockQuote, KLineData, FinancialData,
    CapitalFlowData, MarketSentimentData,
)
from utils.logger import logger

# akshare中列名与系统内部列名的映射
KLINE_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "change_pct",
    "涨跌额": "change_amount",
    "换手率": "turnover",
}


class AkshareFetcher(DataFetcher):
    """
    Akshare数据源实现
    =================
    基于akshare库获取沪深A股各项数据。
    内置请求重试、超时处理和异常降级机制。
    """

    def __init__(self, timeout: int = 30, max_retries: int = 3, retry_delay: float = 1.0):
        """
        Args:
            timeout: 请求超时秒数
            max_retries: 最大重试次数
            retry_delay: 重试初始延迟（指数退避）
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        # 股票名称缓存
        self._name_cache: Dict[str, str] = {}

    # ======================== 内部工具方法 ========================

    def _with_retry(self, func, *args, **kwargs):
        """带重试的函数调用包装器，使用指数退避策略"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(f"请求失败（第{attempt + 1}次），{delay:.1f}秒后重试: {e}")
                    time.sleep(delay)
        raise last_error

    @staticmethod
    def _to_float(val, default: float = 0.0) -> float:
        """安全转换为float，失败返回默认值"""
        try:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _to_optional_float(val) -> Optional[float]:
        """安全转换为Optional[float]，失败返回None"""
        try:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _normalize_code(code: str) -> str:
        """标准化股票代码（去掉前缀如 sh/sz）"""
        code = code.strip().upper()
        # 如果包含 . 则取后半部分
        if "." in code:
            code = code.split(".")[-1]
        return code

    # ======================== DataFetcher接口实现 ========================

    def get_realtime_quote(self, codes: List[str]) -> Dict[str, StockQuote]:
        """获取指定股票列表的实时行情"""
        if not codes:
            return {}

        logger.info(f"获取实时行情: {len(codes)}只股票")
        try:
            df = self._with_retry(ak.stock_zh_a_spot_em)
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return {}

        # 标准化代码列表
        target_codes = set(self._normalize_code(c) for c in codes)
        result = {}

        for _, row in df.iterrows():
            code = self._normalize_code(str(row.get("代码", "")))
            if code not in target_codes:
                continue

            try:
                quote = StockQuote(
                    code=code,
                    name=str(row.get("名称", "")),
                    price=self._to_float(row.get("最新价")),
                    change_pct=self._to_float(row.get("涨跌幅")),
                    change_amount=self._to_float(row.get("涨跌额")),
                    volume=self._to_float(row.get("成交量")),
                    amount=self._to_float(row.get("成交额")),
                    turnover=self._to_float(row.get("换手率")),
                    amplitude=self._to_float(row.get("振幅")),
                    high=self._to_float(row.get("最高")),
                    low=self._to_float(row.get("最低")),
                    open=self._to_float(row.get("今开")),
                    pre_close=self._to_float(row.get("昨收")),
                    pe_dynamic=self._to_optional_float(row.get("市盈率-动态")),
                    pb=self._to_optional_float(row.get("市净率")),
                    total_market_cap=self._to_optional_float(row.get("总市值")),
                    circulating_market_cap=self._to_optional_float(row.get("流通市值")),
                )
                result[code] = quote
                self._name_cache[code] = quote.name
            except Exception as e:
                logger.warning(f"解析股票 {code} 行情失败: {e}")
                continue

        logger.info(f"成功获取 {len(result)}/{len(codes)} 只股票行情")
        return result

    def get_history_kline(
        self,
        code: str,
        period: str = "daily",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> KLineData:
        """获取单只股票的历史K线数据"""
        code = self._normalize_code(code)

        # 默认获取最近250个交易日
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start = datetime.now() - timedelta(days=400)
            start_date = start.strftime("%Y%m%d")

        logger.info(f"获取K线数据: {code} {period} {start_date}-{end_date} {adjust}")

        try:
            df = self._with_retry(
                ak.stock_zh_a_hist,
                symbol=code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        except Exception as e:
            logger.error(f"获取K线数据失败 {code}: {e}")
            return KLineData(code=code, period=period, adjust=adjust)

        if df is None or df.empty:
            logger.warning(f"K线数据为空: {code}")
            return KLineData(code=code, period=period, adjust=adjust)

        # 重命名列
        df = df.rename(columns=KLINE_COLUMN_MAP)
        # 确保必要的列存在
        required_cols = ["date", "open", "close", "high", "low", "volume", "amount"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0.0

        name = self.get_stock_name(code)
        return KLineData(code=code, name=name, df=df, period=period, adjust=adjust)

    def get_financial_data(self, code: str) -> FinancialData:
        """获取单只股票的财务数据"""
        code = self._normalize_code(code)
        name = self.get_stock_name(code)
        logger.info(f"获取财务数据: {code}")

        result = FinancialData(code=code, name=name)

        try:
            # 获取财务指标摘要
            df = self._with_retry(ak.stock_financial_abstract_ths, symbol=code, indicator="按报告期")
            if df is not None and not df.empty:
                latest = df.iloc[-1] if len(df) > 0 else df.iloc[0]
                result.roe = self._to_optional_float(latest.get("净资产收益率"))
                result.revenue_growth = self._to_optional_float(latest.get("营业收入同比增长率"))
                result.profit_growth = self._to_optional_float(latest.get("净利润同比增长率"))
                result.gross_margin = self._to_optional_float(latest.get("销售毛利率"))
                result.net_margin = self._to_optional_float(latest.get("销售净利率"))
                result.debt_ratio = self._to_optional_float(latest.get("资产负债率"))
                result.report_date = str(latest.get("报告期", ""))
        except Exception as e:
            logger.warning(f"获取财务摘要失败 {code}: {e}")

        try:
            # 获取估值指标
            info_df = self._with_retry(ak.stock_individual_info_em, symbol=code)
            if info_df is not None and not info_df.empty:
                info_dict = dict(zip(info_df["item"], info_df["value"]))
                result.pe = self._to_optional_float(info_dict.get("市盈率-动态"))
                result.pb = self._to_optional_float(info_dict.get("市净率"))
                result.total_market_cap = self._to_optional_float(info_dict.get("总市值"))
        except Exception as e:
            logger.warning(f"获取个股信息失败 {code}: {e}")

        return result

    def get_capital_flow(self, code: str) -> CapitalFlowData:
        """获取单只股票的资金流向数据"""
        code = self._normalize_code(code)
        name = self.get_stock_name(code)
        logger.info(f"获取资金流向: {code}")

        result = CapitalFlowData(code=code, name=name)

        try:
            # 获取个股资金流向
            df = self._with_retry(ak.stock_individual_fund_flow, stock=code, market="sh")
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                result.main_net_inflow = self._to_optional_float(latest.get("主力净流入-净额"))
                result.super_large_net_inflow = self._to_optional_float(latest.get("超大单净流入-净额"))
                result.large_net_inflow = self._to_optional_float(latest.get("大单净流入-净额"))
                result.medium_net_inflow = self._to_optional_float(latest.get("中单净流入-净额"))
                result.small_net_inflow = self._to_optional_float(latest.get("小单净流入-净额"))
        except Exception as e:
            logger.warning(f"获取资金流向失败 {code}: {e}")

        return result

    def get_market_sentiment(self) -> MarketSentimentData:
        """获取全市场情绪数据"""
        logger.info("获取市场情绪数据")

        result = MarketSentimentData()

        try:
            # 获取全市场实时行情统计
            df = self._with_retry(ak.stock_zh_a_spot_em)
            if df is not None and not df.empty:
                result.advance_count = int((df["涨跌幅"] > 0).sum())
                result.decline_count = int((df["涨跌幅"] < 0).sum())
                result.flat_count = int((df["涨跌幅"] == 0).sum())

                # 涨停跌停统计（涨跌幅>=9.5%视为涨停，<=-9.5%视为跌停）
                result.limit_up_count = int((df["涨跌幅"] >= 9.5).sum())
                result.limit_down_count = int((df["涨跌幅"] <= -9.5).sum())

                # 计算市场热度指数
                total = result.advance_count + result.decline_count + result.flat_count
                if total > 0:
                    # 上涨比例
                    advance_ratio = result.advance_count / total
                    # 涨停比例（归一化）
                    limit_up_ratio = min(result.limit_up_count / max(total * 0.01, 1), 1.0)
                    # 热度指数 = 上涨比例×60 + 涨停信号×40
                    result.market_heat_index = round(advance_ratio * 60 + limit_up_ratio * 40, 1)
        except Exception as e:
            logger.warning(f"获取市场情绪失败: {e}")

        # 北向资金总体流向
        try:
            north_df = self._with_retry(ak.stock_hsgt_hist_em, symbol="北向资金")
            if north_df is not None and not north_df.empty:
                latest = north_df.iloc[-1]
                result.north_total_inflow = self._to_optional_float(latest.get("当日成交净买额"))
        except Exception as e:
            logger.warning(f"获取北向资金失败: {e}")

        return result

    def get_all_stocks_spot(self) -> pd.DataFrame:
        """获取全市场A股实时行情快照（统一英文列名）"""
        logger.info("获取全市场A股实时行情")
        try:
            df = self._with_retry(ak.stock_zh_a_spot_em)
            # 统一列名为英文，保持与EastMoney/Baostock一致
            COLUMN_MAP = {
                "代码": "code", "名称": "name",
                "最新价": "price", "涨跌幅": "change_pct",
                "涨跌额": "change_amount", "成交量": "volume",
                "成交额": "amount", "换手率": "turnover",
                "振幅": "amplitude", "最高": "high", "最低": "low",
                "今开": "open", "昨收": "pre_close",
                "市盈率-动态": "pe", "市净率": "pb",
                "总市值": "total_market_cap", "流通市值": "circulating_market_cap",
            }
            df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})
            logger.info(f"获取全市场A股行情: {len(df)}只股票")
            return df
        except Exception as e:
            logger.error(f"获取全市场A股行情失败: {e}")
            return pd.DataFrame()

    def get_index_components(self, index_code: str) -> List[str]:
        """获取指数成分股代码列表"""
        logger.info(f"获取指数成分股: {index_code}")

        try:
            if index_code == "000300":
                df = self._with_retry(ak.index_stock_cons_csindex, symbol="000300")
            elif index_code == "000905":
                df = self._with_retry(ak.index_stock_cons_csindex, symbol="000905")
            elif index_code == "000016":
                df = self._with_retry(ak.index_stock_cons_csindex, symbol="000016")
            else:
                logger.warning(f"不支持的指数代码: {index_code}")
                return []

            if df is not None and not df.empty:
                codes = [
                    self._normalize_code(str(c))
                    for c in df["成分券代码"].tolist()
                ]
                logger.info(f"获取 {index_code} 成分股: {len(codes)}只")
                return codes
        except Exception as e:
            logger.error(f"获取指数成分股失败 {index_code}: {e}")

        return []

    def get_stock_name(self, code: str) -> str:
        """根据股票代码获取股票名称"""
        code = self._normalize_code(code)

        # 先查缓存
        if code in self._name_cache:
            return self._name_cache[code]

        # 尝试从全市场行情中查找
        try:
            df = self.get_all_stocks_spot()
            if not df.empty:
                match = df[df["code"].apply(self._normalize_code) == code]
                if not match.empty:
                    name = str(match.iloc[0].get("name", code))
                    self._name_cache[code] = name
                    return name
        except Exception:
            pass

        return code

    def search_stocks(self, keyword: str) -> List[Dict[str, str]]:
        """按关键字搜索股票"""
        keyword = keyword.strip().upper()
        logger.info(f"搜索股票: {keyword}")

        results = []
        try:
            df = self.get_all_stocks_spot()
            if df.empty:
                return results

            for _, row in df.iterrows():
                code = self._normalize_code(str(row.get("code", "")))
                name = str(row.get("name", ""))
                # 按代码或名称匹配
                if keyword in code or keyword in name:
                    results.append({"code": code, "name": name})
                    if len(results) >= 20:  # 最多返回20条
                        break
        except Exception as e:
            logger.error(f"搜索股票失败: {e}")

        return results
