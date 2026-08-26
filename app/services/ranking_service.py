"""
选股排名服务 — 异步编排多因子计算流程
"""
import asyncio
import uuid
import json
import time
from typing import Dict, Any, Optional
import pandas as pd

import sys, os
# 确保项目根目录在路径中（仅当需要时）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.logger import logger

# 导入共享数据函数（非侵入式，不再依赖 main.py）
from data.data_utils import fetch_stock_data, fetch_financial_data, build_demo_strategy


# 因子元信息：因子名 → 中文标签 / 一句话说明 / 原始值格式化类型
# fmt: "pct"=百分比(如 +12.3%)， "num"=数值(如 18.29)
FACTOR_META = {
    "momentum_20":       {"label": "20日动量",   "desc": "近20日涨跌幅，涨得多分高",          "fmt": "pct"},
    "volatility_20":     {"label": "低波动率",   "desc": "波动越低分越高（稳健）",            "fmt": "pct"},
    "volume_price_corr": {"label": "量价配合",   "desc": "量价正相关，量增价涨分高",          "fmt": "num"},
    "rsi_14":            {"label": "RSI(14)",    "desc": "RSI越低分越高（超卖反弹）",          "fmt": "num"},
    "ma_deviation_20":   {"label": "均线偏离",   "desc": "价格低于均线越多分越高",            "fmt": "pct"},
    "reversal_5":        {"label": "5日反转",    "desc": "近5日跌幅大分高（超跌）",           "fmt": "pct"},
    "turnover_20":       {"label": "换手率",     "desc": "换手越活跃分越高",                  "fmt": "pct"},
    "pe":                {"label": "低市盈率PE", "desc": "PE越低分越高（估值便宜）",          "fmt": "num"},
    "pb":                {"label": "低市净率PB", "desc": "PB越低分越高",                      "fmt": "num"},
    "roe":               {"label": "高ROE",      "desc": "ROE越高分越高（盈利强）",           "fmt": "pct"},
    "revenue_growth":    {"label": "营收增长",   "desc": "营收增速越高分越高",                "fmt": "pct"},
    "profit_growth":     {"label": "利润增长",   "desc": "利润增速越高分越高",                "fmt": "pct"},
    "debt_ratio":        {"label": "低负债率",   "desc": "负债率越低分越高",                  "fmt": "pct"},
    "gross_margin":      {"label": "高毛利率",   "desc": "毛利率越高分越高",                  "fmt": "pct"},
}


def _fmt_raw(fmt: str, raw) -> str:
    """按因子类型格式化原始值"""
    if raw is None:
        return "-"
    try:
        v = float(raw)
    except (ValueError, TypeError):
        return "-"
    if fmt == "pct":
        return f"{v:+.1f}%"
    return f"{v:.2f}"


class RankingService:
    """选股排名服务"""

    _instance = None

    def __init__(self, fetcher, raw_fetcher, config: dict):
        self.fetcher = fetcher
        self.raw_fetcher = raw_fetcher
        self.config = config
        self._tasks: Dict[str, Dict] = {}
        RankingService._instance = self

    @classmethod
    def instance(cls):
        return cls._instance

    async def start_ranking(
        self, pool: str = "popular", tech_weight: float = 0.40,
        fund_weight: float = 0.60, top_n: int = 20,
        normalization: str = "rank",
        tech_factors: str = "momentum,volatility,volume_corr",
        fund_factors: str = "pe,roe,revenue",
        tech_weights: str = "",
        fund_weights: str = "",
        filters: dict = None,
    ) -> str:
        """启动异步排名计算"""
        task_id = str(uuid.uuid4())[:8]
        self._tasks[task_id] = {
            "status": "running",
            "progress": 0,
            "step": "初始化...",
            "results": None,
            "summary": None,
        }

        # 异步执行（不阻塞请求）
        asyncio.create_task(
            self._run_ranking(task_id, pool, tech_weight, fund_weight, top_n, normalization, tech_factors, fund_factors, tech_weights, fund_weights, filters or {})
        )
        return task_id

    def _build_stock_pool(self, pool: str) -> list:
        """构建实时股票池，替代硬编码 POPULAR_STOCKS"""
        logger.info(f"构建股票池: {pool}")
        fetcher = self.raw_fetcher

        # 自选股池
        if pool == "watchlist":
            from app.dependencies import get_stock_manager
            mgr = get_stock_manager()
            wl = mgr.load_watchlist()
            wl_stocks = wl.get("stocks", [])
            if wl_stocks:
                result = [{"code": s["code"], "name": s.get("name", s["code"]), "sector": ""} for s in wl_stocks]
                logger.info(f"自选股池: {len(result)}只")
                return result
            logger.info("自选股为空，回退到热门池")
            pool = "popular"

        # 指数成分股池
        index_map = {
            "hs300": "000300",
            "zz500": "000905",
            "sz50": "000016",
        }
        if pool in index_map:
            try:
                codes = fetcher.get_index_components(index_map[pool]) or []
                if codes and len(codes) >= 20:
                    result = [{"code": c, "name": c, "sector": ""} for c in codes]
                    logger.info(f"{pool} 成分股: {len(result)}只")
                    return result
                logger.warning(f"{pool} 成分股获取为空或太少({len(codes) if codes else 0}只)，回退到热门池")
            except Exception as e:
                logger.warning(f"{pool} 成分股获取失败({e})，回退到热门池")

        # baostock 兜底时：无真实行情/成交额，全市场排序无意义且顺序获取慢，
        # 直接用精选硬编码池（约76只），保证选股能在可接受时间内出结果
        if "baostock" in type(fetcher).__name__.lower() and pool in ("popular", "all", "default"):
            from config.stock_lists import POPULAR_STOCKS
            logger.info(f"baostock 兜底：{pool} 池使用精选硬编码池 {len(POPULAR_STOCKS)}只")
            return list(POPULAR_STOCKS)

        # 全市场股票池（default/popular/all）
        try:
            df = fetcher.get_all_stocks_spot()
            if df.empty:
                logger.warning("全市场行情为空，使用应急硬编码池")
                from config.stock_lists import POPULAR_STOCKS
                return list(POPULAR_STOCKS)

            # 过滤：有价格
            if "price" in df.columns:
                df = df[df["price"] > 0].copy()
            if df.empty:
                from config.stock_lists import POPULAR_STOCKS
                return list(POPULAR_STOCKS)

            # 按成交量/成交额排序（兼容不同数据源的列名）
            sort_col = "amount" if "amount" in df.columns else "volume"
            if sort_col not in df.columns:
                sort_col = df.columns[0]

            if pool == "popular" or pool in index_map:
                pool_size = 300
            elif pool == "all":
                pool_size = 2000
            else:
                pool_size = 500

            df = df.sort_values(sort_col, ascending=False).head(pool_size).copy()

            result = [
                {"code": row["code"], "name": row.get("name", row["code"]), "sector": ""}
                for _, row in df.iterrows()
            ]
            logger.info(f"实时股票池 ({pool}): {len(result)}只")
            return result

        except Exception as e:
            logger.error(f"构建股票池失败({e})，使用应急池")
            from config.stock_lists import POPULAR_STOCKS
            return list(POPULAR_STOCKS)

    async def _run_ranking(self, task_id, pool, tech_weight, fund_weight, top_n, normalization, tech_factors, fund_factors, tech_weights, fund_weights, filters):
        """执行完整的选股排名流程"""
        try:
            # 解析因子权重 JSON → {因子名: 权重}；非法/缺省回退空 dict（等权）
            tech_w = self._parse_weights(tech_weights)
            fund_w = self._parse_weights(fund_weights)

            self._update(task_id, 5, f"构建{pool}股票池...")
            stock_pool = self._build_stock_pool(pool)
            stock_codes = [s["code"] for s in stock_pool]

            # 预筛选：用实时行情数据先过滤明显不符合的
            self._update(task_id, 8, "预筛选...")
            try:
                spot_df = self.raw_fetcher.get_all_stocks_spot()
                if not spot_df.empty:
                    spot_index = {r["code"]: r for _, r in spot_df.iterrows()}
                    filtered = []
                    for s in stock_pool:
                        code = s["code"]
                        spot = spot_index.get(code)
                        if spot is None:
                            continue
                        price = float(spot.get("price", 0) or 0)
                        mcap = float(spot.get("total_market_cap", 0) or 0)
                        # 过滤：有价格；东财要求非零市值，估算源(baostock 无真实市值)放宽
                        is_estimated = bool(spot.get("estimated", False))
                        if price > 0 and (mcap > 0 or is_estimated):
                            filtered.append(s)
                    stock_pool = filtered
                    stock_codes = [s["code"] for s in stock_pool]
                    logger.info(f"预筛选后: {len(stock_pool)}只")
            except Exception as e:
                logger.debug(f"预筛选跳过: {e}")

            # 获取K线（使用data_utils的智能方法，自动处理批量/顺序切换）
            self._update(task_id, 10, f"获取K线数据({len(stock_codes)}只)...")
            from data.data_utils import fetch_stock_data
            kline_data = await asyncio.to_thread(
                fetch_stock_data, self.raw_fetcher, stock_codes, 120
            )

            if len(kline_data) < 5:
                self._tasks[task_id] = {
                    "status": "error", "error": f"K线数据不足（{len(kline_data)}只有效），可能非交易时间",
                    "progress": 100, "step": "失败"
                }
                return

            valid_codes = list(kline_data.keys())
            self._update(task_id, 50, f"获取财务数据({len(valid_codes)}只)...")

            # 获取财务数据（使用data_utils的智能方法）
            from data.data_utils import fetch_financial_data
            financial_raw = await asyncio.to_thread(
                fetch_financial_data, self.raw_fetcher, valid_codes
            )
            # 转为期望的格式
            financial_data = {}
            for code, fin in financial_raw.items():
                if fin and fin.get("pe"):
                    financial_data[code] = fin
            logger.info(f"有效财务数据: {len(financial_data)}/{len(valid_codes)}只有效")

            # 构建策略
            self._update(task_id, 70, "计算多因子评分...")
            from factor_combiner import FactorCombiner
            from factor_technical import (
                Momentum20Factor, Volatility20Factor, VolumePriceCorrFactor,
                RSIFactor, MADeviationFactor, Reversal5Factor, Turnover20Factor,
            )
            from factor_fundamental import (
                PEFactor, ROEFactor, RevenueGrowthFactor,
                PBFactor, ProfitGrowthFactor, DebtRatioFactor, GrossMarginFactor,
            )

            combiner = FactorCombiner({
                "strategy": {
                    "technical_weight": tech_weight,
                    "fundamental_weight": fund_weight,
                    "top_n": top_n,
                    "normalization": normalization,
                }
            })

            # 动态构建技术因子
            tech_factor_map = {
                "momentum": Momentum20Factor,
                "volatility": Volatility20Factor,
                "volume_corr": VolumePriceCorrFactor,
                "rsi": RSIFactor,
                "ma_dev": MADeviationFactor,
                "reversal": Reversal5Factor,
                "turnover": Turnover20Factor,
            }
            selected_tech = []
            tf_list = [f.strip() for f in tech_factors.split(",") if f.strip()]
            n_tech = len(tf_list) if tf_list else 1
            for fname in tf_list:
                cls = tech_factor_map.get(fname)
                if cls:
                    # 使用传入的因子权重（缺省等权 1.0）
                    selected_tech.append(cls(weight=tech_w.get(fname, 1.0 / n_tech)))

            # 动态构建基本面因子
            fund_factor_map = {
                "pe": PEFactor,
                "roe": ROEFactor,
                "revenue": RevenueGrowthFactor,
                "pb": PBFactor,
                "profit": ProfitGrowthFactor,
                "debt": DebtRatioFactor,
                "margin": GrossMarginFactor,
            }
            selected_fund = []
            ff_list = [f.strip() for f in fund_factors.split(",") if f.strip()]
            n_fund = len(ff_list) if ff_list else 1
            for fname in ff_list:
                cls = fund_factor_map.get(fname)
                if cls:
                    selected_fund.append(cls(weight=fund_w.get(fname, 1.0 / n_fund)))

            if not selected_tech:
                selected_tech = [Momentum20Factor(weight=1.0)]
            if not selected_fund:
                selected_fund = [PEFactor(weight=1.0)]

            combiner.set_factors(selected_tech, selected_fund)

            self._update(task_id, 85, "综合打分...")
            results = await asyncio.to_thread(
                combiner.compute, kline_data, financial_data
            )

            # 补全名称
            name_map = {s["code"]: s.get("name", s["code"]) for s in stock_pool}
            for code in results["code"].tolist():
                if code not in name_map:
                    try:
                        name_map[code] = self.raw_fetcher.get_stock_name(code) or code
                    except:
                        name_map[code] = code

            if not results.empty:
                results["name"] = results["code"].map(name_map)

            # ===== 应用筛选条件 =====
            if filters:
                self._update(task_id, 90, "应用筛选条件...")
                results = self._apply_filters(results, financial_data, kline_data, filters)
                if results.empty:
                    self._tasks[task_id] = {
                        "status": "error", "error": "筛选后无股票符合条件，请放宽筛选条件",
                        "progress": 100, "step": "筛选后无结果"
                    }
                    return

            # 构建结果
            summary = combiner.get_summary() if hasattr(combiner, 'get_summary') else {}

            # 因子原始值（factor.name -> Series(index=code)）
            raw_map = {}
            for f in (selected_tech + selected_fund):
                raw_map[f.name] = getattr(f, "_raw_values", None)

            # 因子元信息（供前端渲染图例/说明）
            factor_meta = {}
            for f in selected_tech:
                meta = FACTOR_META.get(f.name, {"label": f.name, "desc": "", "fmt": "num"})
                factor_meta[f.name] = {
                    "label": meta["label"], "desc": meta["desc"], "fmt": meta["fmt"],
                    "direction": f.direction, "weight": round(float(f.weight), 3), "category": "tech",
                }
            for f in selected_fund:
                meta = FACTOR_META.get(f.name, {"label": f.name, "desc": "", "fmt": "num"})
                factor_meta[f.name] = {
                    "label": meta["label"], "desc": meta["desc"], "fmt": meta["fmt"],
                    "direction": f.direction, "weight": round(float(f.weight), 3), "category": "fund",
                }

            result_list = []
            if not results.empty:
                factor_cols = [c for c in results.columns if c.startswith("factor_")]
                for _, row in results.iterrows():
                    code = row.get("code", "")
                    # 因子明细：{因子名: {label, score, raw_text, direction, weight, desc}}
                    factors = {}
                    for c in factor_cols:
                        fname = c[len("factor_"):]
                        score = row.get(c)
                        if score is None or pd.isna(score):
                            continue
                        meta = factor_meta.get(fname, {"label": fname, "desc": "", "fmt": "num", "direction": 1, "weight": 0})
                        raw = None
                        raw_series = raw_map.get(fname)
                        if raw_series is not None:
                            try:
                                raw = raw_series.get(code)
                            except Exception:
                                raw = None
                        factors[fname] = {
                            "label": meta["label"],
                            "score": round(float(score), 1),
                            "raw_text": _fmt_raw(meta["fmt"], raw),
                            "direction": meta["direction"],
                            "weight": meta["weight"],
                            "category": meta.get("category", ""),
                            "desc": meta["desc"],
                        }
                    item = {
                        "code": code,
                        "name": row.get("name", ""),
                        "total_score": round(float(row.get("total_score", 0)), 1),
                        "tech_score": round(float(row.get("tech_score", 0)), 1),
                        "fund_score": round(float(row.get("fund_score", 0)), 1),
                        "rank": int(row.get("rank", 0)),
                        "factors": factors,
                    }
                    result_list.append(item)

            self._tasks[task_id] = {
                "status": "done",
                "progress": 100,
                "step": "完成",
                "results": result_list,
                "summary": {
                    "total_stocks": len(result_list),
                    "mean_score": round(float(results["total_score"].mean()), 1) if not results.empty else 0,
                    "max_score": round(float(results["total_score"].max()), 1) if not results.empty else 0,
                    "min_score": round(float(results["total_score"].min()), 1) if not results.empty else 0,
                    "tech_weight": tech_weight,
                    "fund_weight": fund_weight,
                    "pool": pool,
                    "normalization": normalization,
                    "factor_meta": factor_meta,
                },
            }
            logger.info(f"排名计算完成: {len(result_list)}只")

        except Exception as e:
            logger.exception(f"排名计算失败: {e}")
            self._tasks[task_id] = {
                "status": "error",
                "error": str(e),
                "progress": 0,
                "step": "失败",
            }

    def _update(self, task_id, progress, step):
        if task_id in self._tasks:
            self._tasks[task_id]["progress"] = progress
            self._tasks[task_id]["step"] = step

    @staticmethod
    def _parse_weights(weights_str: str) -> dict:
        """解析因子权重 JSON → {因子名: 权重}；非法/缺省返回空 dict"""
        if not weights_str:
            return {}
        try:
            data = json.loads(weights_str)
            if not isinstance(data, dict):
                return {}
            return {k: float(v) for k, v in data.items()}
        except (ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _apply_filters(self, results, financial_data: dict, kline_data: dict, filters: dict):
        """应用自定义筛选条件"""
        import pandas as pd
        mask = pd.Series(True, index=results.index)

        # 从K线数据提取最新收盘价
        latest_prices = {}
        for code, df in kline_data.items():
            if df is not None and not df.empty and "close" in df.columns:
                close = df["close"].iloc[-1]
                try:
                    latest_prices[code] = float(close)
                except (ValueError, TypeError):
                    pass

        for code, fin in financial_data.items():
            if code not in results["code"].values:
                continue
            idx = results[results["code"] == code].index
            if len(idx) == 0:
                continue
            i = idx[0]

            # fin 为 dict（fetch_financial_data 返回 {code: {指标: 值}}），
            # 兼容 dict 与 FinancialData 对象两种来源
            get = fin.get if isinstance(fin, dict) else lambda k: getattr(fin, k, None)

            # PE筛选（上限）
            pe = get("pe")
            if "pe" in filters and pe is not None:
                try:
                    if pe > float(filters["pe"]) or pe <= 0:
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # PB筛选（上限）
            pb = get("pb")
            if "pb" in filters and pb is not None:
                try:
                    if pb > float(filters["pb"]) or pb <= 0:
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # ROE筛选（下限）
            roe = get("roe")
            if "roe" in filters and roe is not None:
                try:
                    if roe < float(filters["roe"]):
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # 营收增长率筛选（下限）
            rev = get("revenue_growth")
            if "rev" in filters and rev is not None:
                try:
                    if rev < float(filters["rev"]):
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # 利润增长率筛选（下限）
            prof = get("profit_growth")
            if "prof" in filters and prof is not None:
                try:
                    if prof < float(filters["prof"]):
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # 毛利率筛选（下限）
            gm = get("gross_margin")
            if "gm" in filters and gm is not None:
                try:
                    if gm < float(filters["gm"]):
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # 资产负债率筛选（上限）
            debt = get("debt_ratio")
            if "debt" in filters and debt is not None:
                try:
                    if debt > float(filters["debt"]):
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # 市值筛选（下限，单位：亿）
            mcap = get("total_market_cap")
            if "mcap" in filters and mcap is not None:
                try:
                    if mcap / 1e8 < float(filters["mcap"]):
                        mask[i] = False
                except (ValueError, TypeError):
                    pass

            # 价格筛选（最新收盘价，从K线数据提取）
            if code in latest_prices:
                price = latest_prices[code]
                if "price_min" in filters:
                    try:
                        if price < float(filters["price_min"]):
                            mask[i] = False
                    except:
                        pass
                if "price_max" in filters:
                    try:
                        if price > float(filters["price_max"]):
                            mask[i] = False
                    except:
                        pass

        filtered = results[mask].copy()
        # 重新排名
        if not filtered.empty:
            filtered = filtered.sort_values("total_score", ascending=False)
            filtered["rank"] = range(1, len(filtered) + 1)

        # 行业筛选
        if "sector" in filters:
            target_sectors = [s.strip() for s in filters["sector"].split(",") if s.strip()]
            if target_sectors:
                from config.stock_lists import POPULAR_STOCKS
                sector_map = {s["code"]: s.get("sector", "") for s in POPULAR_STOCKS}
                sector_mask = pd.Series(False, index=filtered.index)
                for i, row in filtered.iterrows():
                    code = row["code"]
                    stock_sector = sector_map.get(code, "")
                    if any(ts in stock_sector for ts in target_sectors):
                        sector_mask[i] = True
                filtered = filtered[sector_mask]

        n_before = len(results)
        n_after = len(filtered)
        if n_before != n_after:
            logger.info(f"筛选: {n_before} → {n_after} 只 (剔除 {n_before - n_after})")

        return filtered

    def get_task_status(self, task_id: str) -> Optional[dict]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        return {
            "status": task["status"],
            "progress": task["progress"],
            "step": task["step"],
            "error": task.get("error"),
        }

    def get_results(self, task_id: str) -> dict:
        task = self._tasks.get(task_id)
        if not task:
            return {"status": "not_found", "message": "任务不存在"}
        if task["status"] == "error":
            return {"status": "error", "error": task.get("error")}
        if task["status"] != "done":
            return {"status": task["status"], "message": "计算中...", "progress": task["progress"]}
        return {
            "status": "done",
            "summary": task.get("summary"),
            "results": task.get("results", []),
        }
