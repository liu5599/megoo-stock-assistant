"""
SQLite缓存引擎
==============
基于 SQLite + Parquet 序列化的本地数据缓存。
采用TTL机制，不同数据类型设置不同的过期时间。
DataFrame自动序列化为Parquet blob存储，读取零拷贝。
"""

import sqlite3
import hashlib
import time
import json
import io
from datetime import datetime
from typing import Optional, Dict, Any
import pandas as pd

from config.settings import AppConfig, default_config
from utils.logger import logger


class DataCache:
    """
    本地数据缓存引擎
    ================
    基于SQLite实现，支持TTL过期机制。
    不同数据类型配置不同的缓存时长：
    - 实时行情: 60秒
    - 历史K线: 1天
    - 财务数据: 7天
    - 市场情绪/资金流向: 5分钟
    """

    # 缓存表DDL
    _TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS cache_entries (
        cache_key   TEXT PRIMARY KEY,
        data_type   TEXT NOT NULL,        -- 'quote' | 'kline' | 'financial' | 'capital_flow' | 'sentiment' | 'spot' | 'components'
        data_blob   BLOB,                  -- Parquet序列化的DataFrame / JSON字符串
        created_at  REAL NOT NULL,         -- 创建时间戳
        ttl_seconds INTEGER NOT NULL,      -- 过期秒数
        metadata    TEXT                    -- 附加元信息JSON
    );
    CREATE INDEX IF NOT EXISTS idx_cache_type ON cache_entries(data_type);
    CREATE INDEX IF NOT EXISTS idx_cache_created ON cache_entries(created_at);
    """

    def __init__(self, db_path: str = "data_cache.db", config: AppConfig = None):
        """
        初始化缓存引擎

        Args:
            db_path: SQLite数据库文件路径
            config: 应用配置（用于获取各类型TTL）
        """
        self.db_path = db_path
        self.config = config or default_config
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        conn = self._get_conn()
        conn.executescript(self._TABLE_DDL)
        conn.commit()
        logger.debug(f"缓存数据库初始化完成: {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """获取或创建数据库连接（懒初始化，支持多线程）"""
        import threading
        thread_id = threading.get_ident()
        if not hasattr(self, '_conns'):
            self._conns = {}
        if thread_id not in self._conns:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._conns[thread_id] = conn
        return self._conns[thread_id]

    @staticmethod
    def _make_key(prefix: str, *args) -> str:
        """
        生成缓存键

        Args:
            prefix: 数据类型前缀
            *args: 构成键的参数

        Returns:
            唯一缓存键
        """
        raw = f"{prefix}:" + ":".join(str(a) for a in args)
        return hashlib.md5(raw.encode()).hexdigest()

    # ======================== 公共接口 ========================

    def get_dataframe(self, cache_key: str) -> Optional[pd.DataFrame]:
        """
        读取DataFrame缓存

        Args:
            cache_key: 缓存键

        Returns:
            缓存的DataFrame，过期或不存在返回None
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data_blob, created_at, ttl_seconds FROM cache_entries WHERE cache_key = ?",
            (cache_key,)
        ).fetchone()

        if row is None:
            return None

        # 检查TTL过期
        age = time.time() - row["created_at"]
        if age > row["ttl_seconds"]:
            logger.debug(f"缓存已过期: {cache_key} (age={age:.0f}s, ttl={row['ttl_seconds']}s)")
            return None

        # 反序列化缓存(先试 pickle；旧 parquet blob 读取失败即命中失效)
        try:
            buf = io.BytesIO(row["data_blob"])
            df = pd.read_pickle(buf)
            logger.debug(f"缓存命中: {cache_key} ({len(df)}行)")
            return df
        except Exception as e:
            logger.warning(f"缓存反序列化失败: {e}")
            return None

    def set_dataframe(self, cache_key: str, data_type: str,
                      df: pd.DataFrame, ttl_seconds: int = None,
                      metadata: Dict[str, Any] = None) -> None:
        """
        写入DataFrame缓存

        Args:
            cache_key: 缓存键
            data_type: 数据类型标识
            df: 要缓存的DataFrame
            ttl_seconds: 过期时间（秒），None则使用默认值
            metadata: 附加元信息
        """
        if df is None or df.empty:
            return

        if ttl_seconds is None:
            ttl_seconds = self._get_default_ttl(data_type)

        conn = self._get_conn()

        # 序列化(pickle 无 pyarrow 依赖；parquet 需 pyarrow/fastparquet 未装会 500)
        buf = io.BytesIO()
        df.to_pickle(buf)
        blob = buf.getvalue()

        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        conn.execute(
            """INSERT OR REPLACE INTO cache_entries
               (cache_key, data_type, data_blob, created_at, ttl_seconds, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cache_key, data_type, blob, time.time(), ttl_seconds, meta_json)
        )
        conn.commit()
        logger.debug(f"缓存写入: {cache_key} ({len(df)}行, ttl={ttl_seconds}s)")

    def get_json(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        读取JSON格式缓存（用于非DataFrame数据）

        Args:
            cache_key: 缓存键

        Returns:
            缓存的字典，过期或不存在返回None
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data_blob, created_at, ttl_seconds FROM cache_entries WHERE cache_key = ?",
            (cache_key,)
        ).fetchone()

        if row is None:
            return None

        age = time.time() - row["created_at"]
        if age > row["ttl_seconds"]:
            return None

        try:
            return json.loads(row["data_blob"].decode("utf-8"))
        except Exception as e:
            logger.warning(f"JSON缓存反序列化失败: {e}")
            return None

    def set_json(self, cache_key: str, data_type: str,
                 data: Dict[str, Any], ttl_seconds: int = None) -> None:
        """
        写入JSON格式缓存

        Args:
            cache_key: 缓存键
            data_type: 数据类型标识
            data: 要缓存的字典
            ttl_seconds: 过期时间（秒）
        """
        if ttl_seconds is None:
            ttl_seconds = self._get_default_ttl(data_type)

        conn = self._get_conn()
        blob = json.dumps(data, ensure_ascii=False).encode("utf-8")

        conn.execute(
            """INSERT OR REPLACE INTO cache_entries
               (cache_key, data_type, data_blob, created_at, ttl_seconds, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cache_key, data_type, blob, time.time(), ttl_seconds, "{}")
        )
        conn.commit()
        logger.debug(f"JSON缓存写入: {cache_key} (ttl={ttl_seconds}s)")

    def invalidate(self, data_type: str = None, pattern: str = None) -> int:
        """
        清除缓存条目

        Args:
            data_type: 按类型清除（None=全部）
            pattern: 按cache_key LIKE匹配清除

        Returns:
            删除条数
        """
        conn = self._get_conn()

        if data_type and pattern:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE data_type = ? AND cache_key LIKE ?",
                (data_type, f"%{pattern}%")
            )
        elif data_type:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE data_type = ?", (data_type,)
            )
        else:
            cursor = conn.execute("DELETE FROM cache_entries")

        conn.commit()
        count = cursor.rowcount
        logger.info(f"缓存清除: {count}条 (type={data_type}, pattern={pattern})")
        return count

    def cleanup_expired(self) -> int:
        """清理所有过期缓存条目"""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM cache_entries WHERE created_at + ttl_seconds < ?",
            (time.time(),)
        )
        conn.commit()
        count = cursor.rowcount
        if count > 0:
            logger.debug(f"清理过期缓存: {count}条")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) as n FROM cache_entries").fetchone()["n"]
        types = conn.execute(
            "SELECT data_type, COUNT(*) as n FROM cache_entries GROUP BY data_type"
        ).fetchall()

        expired = conn.execute(
            "SELECT COUNT(*) as n FROM cache_entries WHERE created_at + ttl_seconds < ?",
            (time.time(),)
        ).fetchone()["n"]

        return {
            "total_entries": total,
            "expired_entries": expired,
            "by_type": {row["data_type"]: row["n"] for row in types},
            "db_path": self.db_path,
            "db_size_mb": self._get_db_size(),
        }

    def close(self) -> None:
        """关闭数据库连接"""
        if hasattr(self, '_conns'):
            for conn in self._conns.values():
                try:
                    conn.close()
                except:
                    pass
            self._conns.clear()
            logger.debug("缓存数据库连接已关闭")

    # ======================== 内部辅助方法 ========================

    def _get_default_ttl(self, data_type: str) -> int:
        """根据数据类型获取默认TTL"""
        ttl_map = {
            "quote": self.config.CACHE_TTL_QUOTE,
            "kline": self.config.CACHE_TTL_KLINE,
            "financial": self.config.CACHE_TTL_FINANCIAL,
            "capital_flow": self.config.CACHE_TTL_CAPITAL_FLOW,
            "sentiment": self.config.CACHE_TTL_SENTIMENT,
            "spot": self.config.CACHE_TTL_QUOTE,
            "components": self.config.CACHE_TTL_KLINE,
        }
        return ttl_map.get(data_type, 300)

    def _get_db_size(self) -> float:
        """获取数据库文件大小（MB）"""
        import os
        try:
            size_bytes = os.path.getsize(self.db_path)
            return round(size_bytes / (1024 * 1024), 2)
        except OSError:
            return 0.0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ======================== 缓存装饰器 ========================

class CachedFetcher:
    """
    缓存装饰器类
    ============
    包装DataFetcher，自动为数据获取方法添加缓存层。
    缓存命中直接返回，未命中则调用原方法并缓存结果。
    """

    def __init__(self, fetcher, cache: DataCache = None):
        """
        Args:
            fetcher: 原始DataFetcher实例
            cache: DataCache实例
        """
        self._fetcher = fetcher
        self._cache = cache or DataCache()

    def __getattr__(self, name):
        """代理属性访问到原始fetcher"""
        return getattr(self._fetcher, name)

    def get_realtime_quote(self, codes):
        """带缓存的实时行情获取"""
        cache_key = self._cache._make_key("quote", *sorted(codes))
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            # 从缓存重建StockQuote对象
            from data.models import StockQuote
            return {
                code: StockQuote(**data)
                for code, data in cached.items()
            }
        # 调用原始方法
        result = self._fetcher.get_realtime_quote(codes)
        # 缓存序列化后的数据
        from dataclasses import asdict
        serializable = {
            code: asdict(quote)
            for code, quote in result.items()
        }
        self._cache.set_json(cache_key, "quote", serializable)
        return result

    def get_history_kline(self, code, period="daily",
                          start_date=None, end_date=None, adjust="qfq"):
        """带缓存的历史K线获取"""
        cache_key = self._cache._make_key(
            "kline", code, period, start_date or "", end_date or "", adjust
        )
        cached_df = self._cache.get_dataframe(cache_key)
        if cached_df is not None:
            from data.models import KLineData
            return KLineData(
                code=code,
                name=self._fetcher.get_stock_name(code),
                df=cached_df,
                period=period,
                adjust=adjust,
            )
        # 调用原始方法
        result = self._fetcher.get_history_kline(
            code, period, start_date, end_date, adjust
        )
        if not result.df.empty:
            self._cache.set_dataframe(
                cache_key, "kline", result.df,
                metadata={"code": code, "period": period, "adjust": adjust}
            )
        return result

    def get_all_stocks_spot(self):
        """带缓存的全市场行情"""
        cache_key = self._cache._make_key("spot")
        cached_df = self._cache.get_dataframe(cache_key)
        if cached_df is not None:
            return cached_df
        df = self._fetcher.get_all_stocks_spot()
        if not df.empty:
            self._cache.set_dataframe(cache_key, "spot", df)
        return df

    def get_index_components(self, index_code):
        """带缓存的指数成分股"""
        cache_key = self._cache._make_key("components", index_code)
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            return cached.get("codes", [])
        codes = self._fetcher.get_index_components(index_code)
        self._cache.set_json(
            cache_key, "components",
            {"codes": codes, "index": index_code}
        )
        return codes

    def get_market_sentiment(self):
        """带缓存的市场情绪"""
        cache_key = self._cache._make_key("sentiment")
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            from data.models import MarketSentimentData
            return MarketSentimentData(**cached)
        result = self._fetcher.get_market_sentiment()
        from dataclasses import asdict
        self._cache.set_json(cache_key, "sentiment", asdict(result))
        return result

    def get_financial_data(self, code):
        """带缓存的财务数据"""
        cache_key = self._cache._make_key("financial", code)
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            from data.models import FinancialData
            return FinancialData(**cached)
        result = self._fetcher.get_financial_data(code)
        from dataclasses import asdict
        self._cache.set_json(cache_key, "financial", asdict(result))
        return result

    def get_capital_flow(self, code):
        """带缓存的资金流向"""
        cache_key = self._cache._make_key("capital_flow", code)
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            from data.models import CapitalFlowData
            return CapitalFlowData(**cached)
        result = self._fetcher.get_capital_flow(code)
        from dataclasses import asdict
        self._cache.set_json(cache_key, "capital_flow", asdict(result))
        return result
