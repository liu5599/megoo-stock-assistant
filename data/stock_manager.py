"""
股票列表管理器
=============
负责股票列表的获取、缓存、搜索和自选股管理。
支持从akshare动态获取指数成分股，以及本地自选股JSON持久化。
"""

import json
import os
from typing import List, Dict, Optional
from datetime import datetime

from config.stock_lists import INDEX_MAP, POPULAR_STOCKS
from utils.logger import logger


class StockManager:
    """
    股票列表管理器
    ==============
    职责：
    - 动态获取指数成分股（沪深300/中证500/上证50等）
    - 全A股列表管理
    - 股票搜索（按代码/名称）
    - 自选股CRUD（JSON持久化）
    """

    def __init__(self, fetcher=None):
        """
        Args:
            fetcher: DataFetcher实例（用于从网络获取成分股）
        """
        self._fetcher = fetcher
        # 内存缓存
        self._stock_list_cache: Dict[str, List[Dict[str, str]]] = {}
        self._all_stocks_cache: Optional[List[Dict[str, str]]] = None
        # 自选股文件路径
        self._watchlist_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "watchlist"
        )
        self._default_watchlist_path = os.path.join(
            self._watchlist_dir, "default_watchlist.json"
        )

    # ======================== 指数成分股 ========================

    def get_hs300_stocks(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        获取沪深300成分股列表

        Args:
            force_refresh: 是否强制刷新（忽略缓存）

        Returns:
            [{'code': '000001', 'name': '平安银行'}, ...]
        """
        return self._get_index_stocks("hs300", "000300", force_refresh)

    def get_zz500_stocks(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """获取中证500成分股列表"""
        return self._get_index_stocks("zz500", "000905", force_refresh)

    def get_sz50_stocks(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """获取上证50成分股列表"""
        return self._get_index_stocks("sz50", "000016", force_refresh)

    def get_all_a_stocks(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """获取全A股列表（含名称）"""
        if self._all_stocks_cache is not None and not force_refresh:
            return self._all_stocks_cache

        if self._fetcher is None:
            logger.warning("未配置DataFetcher，返回热门股票列表作为替代")
            return POPULAR_STOCKS

        try:
            df = self._fetcher.get_all_stocks_spot()
            if df is not None and not df.empty:
                stocks = []
                for _, row in df.iterrows():
                    code = str(row.get("code", "")).strip()
                    name = str(row.get("name", "")).strip()
                    if code and len(code) == 6:
                        stocks.append({"code": code, "name": name})
                self._all_stocks_cache = stocks
                logger.info(f"全A股列表加载完成: {len(stocks)}只")
                return stocks
        except Exception as e:
            logger.error(f"获取全A股列表失败: {e}")

        return POPULAR_STOCKS

    def get_top_n_by_market_cap(self, n: int = 500) -> List[Dict[str, str]]:
        """
        获取沪深A股市值排名前N只股票

        使用东方财富API按总市值降序排列。

        Args:
            n: 返回前N只（默认500）

        Returns:
            [{'code': '600519', 'name': '贵州茅台'}, ...]
        """
        if self._fetcher is None:
            logger.warning("未配置DataFetcher，返回热门股票列表")
            return POPULAR_STOCKS

        try:
            stocks = self._fetcher.get_top_n_by_market_cap(n)
            if stocks:
                logger.info(f"市值排名前{n}: {len(stocks)}只")
                return [{"code": s["code"], "name": s["name"]} for s in stocks]
        except Exception as e:
            logger.error(f"获取市值排名失败: {e}")

        return POPULAR_STOCKS

    def get_index_info(self, pool_name: str) -> Dict[str, str]:
        """获取指数基本信息"""
        info = INDEX_MAP.get(pool_name, {})
        return {
            "name": info.get("name", pool_name),
            "code": info.get("ak_index_code", ""),
            "description": info.get("description", ""),
        }

    def get_stock_pool(self, pool_name: str, force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        根据名称获取对应股票池

        Args:
            pool_name: 'hs300' | 'zz500' | 'sz50' | 'all'
            force_refresh: 是否强制刷新

        Returns:
            股票列表
        """
        pool_methods = {
            "hs300": self.get_hs300_stocks,
            "zz500": self.get_zz500_stocks,
            "sz50": self.get_sz50_stocks,
            "all": self.get_all_a_stocks,
        }

        method = pool_methods.get(pool_name)
        if method is None:
            logger.warning(f"未知股票池: {pool_name}，使用全部A股")
            return self.get_all_a_stocks(force_refresh)

        return method(force_refresh)

    # ======================== 股票搜索 ========================

    def search_stock(self, keyword: str) -> List[Dict[str, str]]:
        """
        按代码或名称模糊搜索股票

        Args:
            keyword: 搜索关键字

        Returns:
            匹配的股票列表，最多20条
        """
        if self._fetcher is not None:
            try:
                results = self._fetcher.search_stocks(keyword)
                if results:
                    return results
            except Exception as e:
                logger.warning(f"在线搜索失败，使用本地缓存: {e}")

        # 本地搜索
        all_stocks = self.get_all_a_stocks()
        keyword_upper = keyword.strip().upper()
        results = []
        for stock in all_stocks:
            if keyword_upper in stock["code"] or keyword_upper in stock["name"].upper():
                results.append(stock)
                if len(results) >= 20:
                    break
        return results

    # ======================== 自选股管理 ========================

    def load_watchlist(self, path: str = None) -> dict:
        """
        加载自选股列表

        Args:
            path: 自选股JSON文件路径

        Returns:
            包含 stocks/count/updated_at 的字典
        """
        if path is None:
            path = self._default_watchlist_path

        if not os.path.exists(path):
            logger.info(f"自选股文件不存在，返回空列表: {path}")
            return {"stocks": [], "count": 0, "updated_at": ""}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stocks = data.get("stocks", [])
            logger.info(f"加载自选股: {len(stocks)}只")
            return {
                "stocks": stocks,
                "count": data.get("count", len(stocks)),
                "updated_at": data.get("updated_at", ""),
            }
        except Exception as e:
            logger.error(f"加载自选股失败: {e}")
            return {"stocks": [], "count": 0, "updated_at": ""}

    def save_watchlist(self, stocks: List[Dict[str, str]], path: str = None) -> None:
        """
        保存自选股列表

        Args:
            stocks: 自选股列表
            path: 保存路径
        """
        if path is None:
            path = self._default_watchlist_path

        os.makedirs(os.path.dirname(path), exist_ok=True)

        data = {
            "updated_at": datetime.now().isoformat(),
            "count": len(stocks),
            "stocks": stocks,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"保存自选股: {len(stocks)}只 -> {path}")
        except Exception as e:
            logger.error(f"保存自选股失败: {e}")
            raise

    def add_to_watchlist(self, codes: List[str], names: Dict[str, str] = None,
                         path: str = None) -> List[Dict[str, str]]:
        """
        添加股票到自选股

        Args:
            codes: 要添加的股票代码列表
            names: 可选，{code: name} 映射。前端搜索选中时传入，避免后端重新查找
            path: 自选股文件路径

        Returns:
            更新后的自选股列表
        """
        watchlist = self.load_watchlist(path).get("stocks", [])
        existing_codes = {s["code"] for s in watchlist}
        names = names or {}

        for code in codes:
            if code not in existing_codes:
                # 优先使用前端传入的名称，其次尝试 fetcher 查询，最后用代码
                name = names.get(code)
                if not name and self._fetcher:
                    try:
                        name = self._fetcher.get_stock_name(code)
                    except Exception:
                        pass
                if not name:
                    name = code
                watchlist.append({"code": code, "name": name})
                existing_codes.add(code)
                logger.info(f"添加自选股: {code} {name}")

        self.save_watchlist(watchlist, path)
        return watchlist

    def remove_from_watchlist(self, codes: List[str], path: str = None) -> List[Dict[str, str]]:
        """
        从自选股移除

        Args:
            codes: 要移除的股票代码列表
            path: 自选股文件路径

        Returns:
            更新后的自选股列表
        """
        watchlist = self.load_watchlist(path).get("stocks", [])
        codes_set = set(codes)
        removed = [s for s in watchlist if s["code"] not in codes_set]
        count = len(watchlist) - len(removed)

        if count > 0:
            self.save_watchlist(removed, path)
            logger.info(f"移除自选股: {count}只")

        return removed

    def get_watchlist_with_quotes(self, path: str = None) -> List[Dict]:
        """
        获取自选股并附带实时行情

        Args:
            path: 自选股文件路径

        Returns:
            带行情数据的自选股列表
        """
        watchlist_dict = self.load_watchlist(path)
        watchlist = watchlist_dict.get("stocks", [])
        if not watchlist or self._fetcher is None:
            return [{"code": s["code"], "name": s["name"], "quote": None}
                    for s in watchlist]

        codes = [s["code"] for s in watchlist]
        try:
            quotes = self._fetcher.get_realtime_quote(codes)
            if quotes is None:
                quotes = {}
        except Exception as e:
            logger.warning(f"获取自选股行情失败: {e}")
            quotes = {}

        result = []
        for stock in watchlist:
            code = stock["code"]
            result.append({
                "code": code,
                "name": stock.get("name", code),
                "quote": quotes.get(code),
            })
        return result

    # ======================== 内部方法 ========================

    def _get_index_stocks(self, pool_name: str, index_code: str,
                          force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        获取指数成分股的通用方法

        Args:
            pool_name: 缓存键名
            index_code: akshare指数代码
            force_refresh: 是否强制刷新

        Returns:
            成分股列表
        """
        # 检查缓存
        if pool_name in self._stock_list_cache and not force_refresh:
            return self._stock_list_cache[pool_name]

        if self._fetcher is None:
            logger.warning(f"未配置DataFetcher，指数 {pool_name} 返回空列表")
            return []

        try:
            codes = self._fetcher.get_index_components(index_code)
            stocks = []
            for code in codes:
                name = code
                try:
                    name = self._fetcher.get_stock_name(code)
                except Exception:
                    pass
                stocks.append({"code": code, "name": name})

            self._stock_list_cache[pool_name] = stocks
            logger.info(f"指数 {pool_name} 成分股: {len(stocks)}只")
            return stocks
        except Exception as e:
            logger.error(f"获取指数成分股失败 {pool_name}: {e}")
            return []

    def clear_cache(self) -> None:
        """清除所有列表缓存"""
        self._stock_list_cache.clear()
        self._all_stocks_cache = None
        logger.info("股票列表缓存已清除")
