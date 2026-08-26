"""
数据获取抽象基类
===============
定义统一的数据获取接口，所有数据源必须实现此接口。
支持通过工厂模式注册和切换不同的数据源（akshare / tushare / baostock）。
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Type
import pandas as pd

from data.models import (
    StockQuote, KLineData, FinancialData,
    CapitalFlowData, MarketSentimentData,
)


class DataFetcher(ABC):
    """
    数据获取抽象基类
    ================
    定义股票数据获取的统一接口。
    所有具体数据源实现（akshare、tushare等）必须继承此类并实现全部抽象方法。
    """

    @abstractmethod
    def get_realtime_quote(self, codes: List[str]) -> Dict[str, StockQuote]:
        """
        获取指定股票列表的实时行情

        Args:
            codes: 股票代码列表，如 ['000001', '600519']

        Returns:
            Dict[str, StockQuote]: 代码到行情对象的映射
        """
        pass

    @abstractmethod
    def get_history_kline(
        self,
        code: str,
        period: str = "daily",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> KLineData:
        """
        获取单只股票的历史K线数据

        Args:
            code: 股票代码
            period: K线周期 ('daily' / 'weekly' / 'monthly')
            start_date: 起始日期 'YYYYMMDD'
            end_date: 结束日期 'YYYYMMDD'
            adjust: 复权方式 (''不复权 / 'qfq'前复权 / 'hfq'后复权)

        Returns:
            KLineData: K线数据对象
        """
        pass

    @abstractmethod
    def get_financial_data(self, code: str) -> FinancialData:
        """
        获取单只股票的财务数据

        Args:
            code: 股票代码

        Returns:
            FinancialData: 财务数据对象
        """
        pass

    @abstractmethod
    def get_capital_flow(self, code: str) -> CapitalFlowData:
        """
        获取单只股票的资金流向数据

        Args:
            code: 股票代码

        Returns:
            CapitalFlowData: 资金流向数据对象
        """
        pass

    @abstractmethod
    def get_market_sentiment(self) -> MarketSentimentData:
        """
        获取全市场情绪数据

        Returns:
            MarketSentimentData: 市场情绪数据对象
        """
        pass

    @abstractmethod
    def get_all_stocks_spot(self) -> pd.DataFrame:
        """
        获取全市场A股实时行情快照

        Returns:
            pd.DataFrame: 包含所有A股的实时行情数据
        """
        pass

    @abstractmethod
    def get_index_components(self, index_code: str) -> List[str]:
        """
        获取指数成分股代码列表

        Args:
            index_code: 指数代码（如 '000300' 沪深300, '000905' 中证500）

        Returns:
            List[str]: 成分股代码列表
        """
        pass

    @abstractmethod
    def get_stock_name(self, code: str) -> str:
        """
        根据股票代码获取股票名称

        Args:
            code: 股票代码

        Returns:
            str: 股票名称
        """
        pass

    @abstractmethod
    def search_stocks(self, keyword: str) -> List[Dict[str, str]]:
        """
        按关键字搜索股票

        Args:
            keyword: 搜索关键字（代码或名称片段）

        Returns:
            List[Dict]: 匹配的股票列表 [{'code': '000001', 'name': '平安银行'}, ...]
        """
        pass


class DataFetcherFactory:
    """
    数据源工厂
    ==========
    根据配置创建对应的DataFetcher实例。
    支持注册自定义数据源，方便扩展。
    """

    _registry: Dict[str, Type[DataFetcher]] = {}

    @classmethod
    def register(cls, name: str, fetcher_cls: Type[DataFetcher]) -> None:
        """
        注册自定义数据源

        Args:
            name: 数据源名称
            fetcher_cls: 数据源实现类
        """
        cls._registry[name] = fetcher_cls

    @classmethod
    def create(cls, source_name: str = "akshare", **kwargs) -> DataFetcher:
        """
        根据数据源名称创建Fetcher实例

        Args:
            source_name: 数据源名称
            **kwargs: 传递给构造函数的关键字参数

        Returns:
            DataFetcher: 数据源实例

        Raises:
            ValueError: 不支持的数据源名称
        """
        # 默认注册 akshare 和 baostock
        if "akshare" not in cls._registry:
            from data.akshare_fetcher import AkshareFetcher
            cls._registry["akshare"] = AkshareFetcher
        if "baostock" not in cls._registry:
            from data.baostock_fetcher import BaostockFetcher
            cls._registry["baostock"] = BaostockFetcher

        fetcher_cls = cls._registry.get(source_name)
        if fetcher_cls is None:
            raise ValueError(
                f"不支持的数据源: {source_name}，"
                f"可用数据源: {list(cls._registry.keys())}"
            )
        return fetcher_cls(**kwargs)
