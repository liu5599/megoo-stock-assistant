"""
市场数据服务 — 指数行情、行业热力图、市场情绪
"""
import asyncio
from typing import Dict, List, Any

from utils.logger import logger


class MarketService:
    """市场总览数据服务"""

    def __init__(self, raw_fetcher):
        self.fetcher = raw_fetcher

    # 腾讯实时行情接口的指数代码映射（一次请求可拿全部）
    _TENCENT_INDEX_MAP = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
        "sh000688": "科创50",
        "sh000300": "沪深300",
        "sh000905": "中证500",
    }

    def _fetch_indices(self):
        """用腾讯实时行情接口一次性获取所有指数（快、准、不依赖K线接口）"""
        import requests
        codes = ",".join(self._TENCENT_INDEX_MAP.keys())
        try:
            r = requests.get(f"https://qt.gtimg.cn/q={codes}", timeout=8)
            r.encoding = "gbk"
            indices = []
            for line in r.text.strip().split(";"):
                line = line.strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                val = val.strip().strip('"')
                parts = val.split("~")
                if len(parts) < 7:
                    continue
                try:
                    price = float(parts[3] or 0)
                    prev_close = float(parts[4] or 0)
                    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
                    indices.append({
                        "code": parts[2],
                        "name": parts[1],
                        "close": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "volume": int(float(parts[6] or 0)),
                    })
                except (ValueError, IndexError):
                    continue
            return indices
        except Exception as e:
            logger.debug(f"腾讯指数获取失败: {e}")
            return []

    async def get_market_overview(self) -> dict:
        """获取市场总览数据（指数/行业并行获取，避免串行超时）"""
        from concurrent.futures import ThreadPoolExecutor

        def _fetch():
            result = {
                "indices": [],
                "sectors": [],
                "breadth": {"up": 0, "down": 0, "flat": 0},
                "timestamp": "",
            }

            try:
                from config.stock_lists import SECTOR_CATEGORIES

                # 指数：腾讯实时行情一次拿全（快）；行业：代表股并行估算
                result["indices"] = self._fetch_indices()
                with ThreadPoolExecutor(max_workers=10) as pool:
                    sec_futs = [pool.submit(self._estimate_sector, s) for s in SECTOR_CATEGORIES[:10]]
                    for f in sec_futs:
                        r = f.result()
                        if r:
                            result["sectors"].append(r)

                # 涨跌统计（可能为估算值，透传 estimated 标记）
                try:
                    sentiment = self.fetcher.get_market_sentiment()
                    if sentiment:
                        result["breadth"] = {
                            "up": getattr(sentiment, "advance_count", 0) or 0,
                            "down": getattr(sentiment, "decline_count", 0) or 0,
                            "flat": getattr(sentiment, "flat_count", 0) or 0,
                            "limit_up": getattr(sentiment, "limit_up_count", 0) or 0,
                            "limit_down": getattr(sentiment, "limit_down_count", 0) or 0,
                            "heat": getattr(sentiment, "market_heat_index", 50) or 50,
                            "estimated": getattr(sentiment, "estimated", True),
                            "source": getattr(sentiment, "source", ""),
                        }
                        total = result["breadth"]["up"] + result["breadth"]["down"] + result["breadth"]["flat"]
                        if total == 0:
                            result["breadth"] = {"up": 0, "down": 0, "flat": 0, "limit_up": 0, "limit_down": 0, "heat": 50, "estimated": True, "source": ""}
                except Exception as e:
                    logger.debug(f"市场情绪获取失败: {e}")

            except Exception as e:
                logger.error(f"市场数据获取失败: {e}")

            from datetime import datetime
            result["timestamp"] = datetime.now().strftime("%H:%M:%S")
            return result

        return await asyncio.to_thread(_fetch)

    def _estimate_sector(self, sector_name: str) -> dict:
        """估算行业板块表现（每行业取 1 只代表股，减少请求次数）"""
        from config.stock_lists import POPULAR_STOCKS
        sector_stocks = [s for s in POPULAR_STOCKS if s.get("sector") == sector_name]
        if not sector_stocks:
            return None

        changes = []
        # 每行业 1 只代表股：东财/腾讯K线全挂时兜底 baostock 亦能返当日数据，
        # 故不再放大样本(baostock 全局串行锁，样本多=冷启动分钟级)
        for s in sector_stocks[:1]:
            try:
                kline = self.fetcher.get_history_kline(s["code"], period="daily", adjust="")
                if kline and not kline.df.empty and len(kline.df) > 1:
                    latest = kline.df.iloc[-1]
                    prev = kline.df.iloc[-2]
                    if prev["close"] != 0:
                        chg = (latest["close"] - prev["close"]) / prev["close"] * 100
                        changes.append(chg)
            except:
                pass

        if not changes:
            return None

        avg_change = sum(changes) / len(changes)
        return {
            "name": sector_name,
            "change_pct": round(avg_change, 2),
            "stock_count": len(sector_stocks),
            "sample_count": len(changes),
        }

    async def get_hot_sectors(self, limit: int = 10) -> list:
        """获取热门行业排名（并行估算）"""
        from config.stock_lists import SECTOR_CATEGORIES
        from concurrent.futures import ThreadPoolExecutor

        def _fetch():
            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(self._estimate_sector, SECTOR_CATEGORIES[:10]))
            sectors = [d for d in results if d]
            sectors.sort(key=lambda x: x["change_pct"], reverse=True)
            return sectors[:limit]

        return await asyncio.to_thread(_fetch)
