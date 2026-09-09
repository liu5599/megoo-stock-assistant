"""
回测服务 — 异步编排回测计算流程
"""
import asyncio
import uuid
import time
from typing import Dict, Any, Optional
import pandas as pd

import sys, os
# 确保项目根目录在路径中（仅当需要时）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from data.data_utils import fetch_stock_data, fetch_financial_data
from backtest_engine import BacktestEngine, BacktestConfig
from utils.logger import logger
from utils.task_store import load_tasks, save_tasks


class BacktestService:
    """回测服务"""

    _instance = None

    def __init__(self, fetcher, raw_fetcher, config: dict):
        self.fetcher = fetcher
        self.raw_fetcher = raw_fetcher
        self.config = config
        self._tasks: Dict[str, Dict] = load_tasks("backtest")
        BacktestService._instance = self

    def _persist(self):
        save_tasks("backtest", self._tasks)

    @classmethod
    def instance(cls):
        return cls._instance

    async def start_backtest(
        self, start_date: str = "20250101", end_date: str = "20260624",
        pool: str = "popular", rebalance_freq: str = "monthly",
        max_positions: int = 20, initial_capital: float = 1_000_000,
        tech_weight: float = 0.40, fund_weight: float = 0.60,
    ) -> str:
        """启动异步回测"""
        task_id = str(uuid.uuid4())[:8]
        self._tasks[task_id] = {
            "status": "running",
            "progress": 0,
            "step": "初始化回测...",
        }

        asyncio.create_task(
            self._run_backtest(
                task_id, start_date, end_date, pool, rebalance_freq,
                max_positions, initial_capital, tech_weight, fund_weight,
            )
        )
        return task_id

    async def _run_backtest(
        self, task_id, start_date, end_date, pool, rebalance_freq,
        max_positions, initial_capital, tech_weight, fund_weight,
    ):
        """执行回测"""
        try:
            self._update(task_id, 5, "构建股票池...")

            from config.stock_lists import POPULAR_STOCKS
            stock_pool = list(POPULAR_STOCKS)
            if pool != "popular":
                try:
                    extra = self.raw_fetcher.get_index_components("000300") or []
                    existing = {s["code"] for s in stock_pool}
                    stock_pool += [{"code": c, "name": c} for c in extra[:20] if c not in existing]
                except:
                    pass

            stock_codes = [s["code"] for s in stock_pool]

            self._update(task_id, 10, "获取历史K线数据...")
            kline_data = await asyncio.to_thread(
                fetch_stock_data, self.fetcher, stock_codes, days=400
            )

            if len(kline_data) < 5:
                self._tasks[task_id] = {
                    "status": "error", "error": "K线数据不足", "progress": 100, "step": "失败"
                }
                self._persist()
                return

            # 获取财务数据（供信号函数里的基本面因子使用）
            self._update(task_id, 35, "获取财务数据...")
            try:
                financial_data = await asyncio.to_thread(
                    fetch_financial_data, self.raw_fetcher, list(kline_data.keys())
                )
            except Exception as e:
                logger.warning(f"回测财务数据获取失败: {e}")
                financial_data = {}

            self._update(task_id, 40, "构建回测引擎...")

            bt_config = BacktestConfig(
                start_date=start_date,
                end_date=end_date,
                rebalance_freq=rebalance_freq,
                max_positions=max_positions,
                initial_capital=initial_capital,
                commission_rate=0.0003,
                slippage=0.001,
            )

            engine = BacktestEngine(bt_config)

            # 信号函数：每个调仓日根据多因子评分选股
            def signal_func(date: str, price_data: dict) -> list:
                try:
                    from factor_combiner import FactorCombiner
                    from factor_technical import Momentum20Factor, Volatility20Factor, VolumePriceCorrFactor
                    from factor_fundamental import PEFactor, ROEFactor, RevenueGrowthFactor

                    # 构建当日数据快照
                    snapshot = {}
                    for code, df in price_data.items():
                        df_sorted = df.sort_values("date")
                        mask = df_sorted["date"] <= date
                        if mask.any():
                            snapshot[code] = df_sorted[mask]

                    if len(snapshot) < 10:
                        return []

                    # 财务数据只保留当日有K线的股票，与 snapshot 对齐
                    fin_snapshot = {c: financial_data.get(c, {}) for c in snapshot}

                    # 简化的因子计算（用K线数据估算）
                    combiner = FactorCombiner({
                        "strategy": {
                            "technical_weight": tech_weight,
                            "fundamental_weight": fund_weight,
                            "top_n": max_positions,
                            "normalization": "rank",
                        }
                    })

                    tech_factors = [
                        Momentum20Factor(weight=1/3),
                        Volatility20Factor(weight=1/3),
                        VolumePriceCorrFactor(weight=1/3),
                    ]
                    fund_factors = [
                        PEFactor(weight=1/3),
                        ROEFactor(weight=1/3),
                        RevenueGrowthFactor(weight=1/3),
                    ]
                    combiner.set_factors(tech_factors, fund_factors)
                    results = combiner.compute(snapshot, fin_snapshot)
                    top = combiner.get_top_n(max_positions)
                    return top["code"].tolist() if not top.empty else []
                except Exception as e:
                    logger.debug(f"信号生成失败 {date}: {e}")
                    return []

            self._update(task_id, 60, "运行回测模拟...")
            result = await asyncio.to_thread(engine.run, kline_data, signal_func)

            self._update(task_id, 90, "计算绩效指标...")

            # 序列化结果
            nav_dates = []
            strategy_nav = []
            benchmark_nav = []
            if result.nav_series is not None and not result.nav_series.empty:
                nav_dates = result.nav_series.index.tolist()
                strategy_nav = [round(v, 4) for v in result.nav_series.values.tolist()]
            if result.benchmark_nav is not None and not result.benchmark_nav.empty:
                benchmark_nav = [round(v, 4) for v in result.benchmark_nav.values.tolist()]

            # 计算回撤序列
            dd_series = []
            if result.nav_series is not None and not result.nav_series.empty:
                peak = result.nav_series.expanding().max()
                dd = (result.nav_series / peak - 1) * 100
                dd_series = [round(v, 2) for v in dd.values.tolist()]

            self._tasks[task_id] = {
                "status": "done",
                "progress": 100,
                "step": "完成",
                "metrics": {
                    "total_return": round(float(result.total_return), 2),
                    "annual_return": round(float(result.annual_return), 2),
                    "annual_volatility": round(float(result.annual_volatility), 2),
                    "sharpe_ratio": round(float(result.sharpe_ratio), 2),
                    "max_drawdown": round(float(result.max_drawdown), 2),
                    "win_rate": round(float(result.win_rate), 1),
                    "total_trades": int(result.total_trades),
                    "benchmark_return": round(float(result.benchmark_return), 2),
                    "excess_return": round(float(result.excess_return), 2),
                    "information_ratio": round(float(result.information_ratio), 2),
                },
                "nav_data": {
                    "dates": [str(d) for d in nav_dates],
                    "strategy_nav": strategy_nav,
                    "benchmark_nav": benchmark_nav,
                    "drawdown": dd_series,
                },
                "position_history": result.position_history if hasattr(result, 'position_history') else [],
                "config": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "rebalance_freq": rebalance_freq,
                    "max_positions": max_positions,
                    "initial_capital": initial_capital,
                    "tech_weight": tech_weight,
                    "fund_weight": fund_weight,
                },
            }

            logger.info(f"回测完成: 总收益 {result.total_return:.2f}%, 夏普 {result.sharpe_ratio:.2f}")
            self._persist()

        except Exception as e:
            logger.exception(f"回测失败: {e}")
            self._tasks[task_id] = {
                "status": "error",
                "error": str(e),
                "progress": 0,
                "step": "失败",
            }
            self._persist()

    def _update(self, task_id, progress, step):
        if task_id in self._tasks:
            self._tasks[task_id]["progress"] = progress
            self._tasks[task_id]["step"] = step
            self._persist()

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

    def get_result(self, task_id: str) -> dict:
        task = self._tasks.get(task_id)
        if not task:
            return {"status": "not_found", "message": "任务不存在"}
        if task["status"] == "error":
            return {"status": "error", "error": task.get("error")}
        if task["status"] != "done":
            return {"status": task["status"], "message": "计算中...", "progress": task["progress"]}
        return {
            "status": "done",
            "metrics": task.get("metrics"),
            "nav_data": task.get("nav_data"),
            "position_history": task.get("position_history", []),
            "config": task.get("config"),
        }
