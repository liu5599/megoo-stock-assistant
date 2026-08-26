"""
FastAPI 依赖注入
提供共享的单例实例：fetcher, cache, config, stock_manager
"""
import os
import yaml
from functools import lru_cache

from data.cache import DataCache, CachedFetcher
from data.eastmoney_fetcher import EastMoneyFetcher
from data.baostock_fetcher import BaostockFetcher
from data.stock_manager import StockManager
from config.settings import AppConfig


_cache_instance = None
_fetcher_instance = None
_stock_manager_instance = None
_config_instance = None


def get_config() -> dict:
    """加载 YAML 配置"""
    global _config_instance
    if _config_instance is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml"
        )
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                _config_instance = yaml.safe_load(f)
        else:
            _config_instance = {}
    return _config_instance


def get_cache() -> DataCache:
    """获取缓存实例"""
    global _cache_instance
    if _cache_instance is None:
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data_cache.db"
        )
        _cache_instance = DataCache(db_path=db_path)
    return _cache_instance


def get_raw_fetcher():
    """获取主数据获取器（自动检测可用数据源：EastMoney → baostock）"""
    global _fetcher_instance
    if _fetcher_instance is None:
        from data.data_utils import get_best_fetcher
        _fetcher_instance = get_best_fetcher()
        from utils.logger import logger
        cls_name = type(_fetcher_instance).__name__
        logger.info(f"✅ 自动选择数据源: {cls_name}")
    return _fetcher_instance


def get_em_fetcher():
    """获取东方财富数据源（用于实时行情、搜索、市场数据）"""
    if not hasattr(get_em_fetcher, '_instance'):
        try:
            get_em_fetcher._instance = EastMoneyFetcher(timeout=15)
            from utils.logger import logger
            logger.info("✅ 东方财富数据源已就绪（实时行情+搜索）")
        except Exception as e:
            get_em_fetcher._instance = get_raw_fetcher()
    return get_em_fetcher._instance


def get_fetcher() -> CachedFetcher:
    """获取带缓存的数据获取器"""
    raw = get_raw_fetcher()
    cache = get_cache()
    return CachedFetcher(fetcher=raw, cache=cache)


def get_stock_manager() -> StockManager:
    """获取股票管理器"""
    global _stock_manager_instance
    if _stock_manager_instance is None:
        _stock_manager_instance = StockManager(fetcher=get_raw_fetcher())
    return _stock_manager_instance
