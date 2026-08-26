"""
回测引擎
=======
支持多因子策略的历史回测，评估策略表现。

功能：
  - 支持自定义调仓周期（每日/每周/每月）
  - 计入手续费和滑点
  - 与基准指数对比（默认沪深300）
  - 输出绩效指标：年化收益率、夏普比率、最大回撤、胜率等

设计模式：
  - 事件驱动，按调仓日推进
  - 持仓管理：等权重配置
"""

from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from utils.logger import logger


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class BacktestConfig:
    """回测配置参数"""
    start_date: str = "20250101"
    end_date: str = "20260621"
    rebalance_freq: str = "monthly"       # daily / weekly / monthly
    commission_rate: float = 0.0003       # 手续费率
    slippage: float = 0.001              # 滑点
    benchmark_code: str = "000300"        # 基准指数
    initial_capital: float = 1_000_000    # 初始资金
    max_positions: int = 20               # 最大持仓数

    @property
    def rebalance_days(self) -> int:
        """调仓间隔（交易日估算）"""
        return {"daily": 1, "weekly": 5, "monthly": 21}.get(
            self.rebalance_freq, 21
        )


@dataclass
class BacktestResult:
    """回测结果"""
    # 收益指标
    total_return: float = 0.0              # 总收益率
    annual_return: float = 0.0            # 年化收益率
    annual_volatility: float = 0.0        # 年化波动率
    sharpe_ratio: float = 0.0             # 夏普比率（无风险利率按2%）
    max_drawdown: float = 0.0             # 最大回撤

    # 交易统计
    win_rate: float = 0.0                 # 胜率（调仓周期胜率）
    total_trades: int = 0                # 总调仓次数

    # 对比基准
    benchmark_return: float = 0.0         # 基准总收益率
    excess_return: float = 0.0            # 超额收益
    information_ratio: float = 0.0        # 信息比率

    # 净值序列
    nav_series: pd.Series = field(default_factory=pd.Series)
    benchmark_nav: pd.Series = field(default_factory=pd.Series)

    # 持仓明细
    position_history: List[Dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 回测引擎
# ═══════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    回测引擎
    ========
    基于历史数据对多因子策略进行回测。

    使用示例:
        >>> engine = BacktestEngine(config)
        >>> result = engine.run(price_data, signal_func)
        >>> engine.print_summary(result)
    """

    # 无风险利率（用于夏普比率计算）
    RISK_FREE_RATE = 0.02

    def __init__(self, config: BacktestConfig):
        """
        Args:
            config: 回测配置
        """
        self.config = config
        self._nav: List[float] = []       # 净值序列
        self._dates: List[str] = []        # 日期序列
        self._positions: Dict[str, float] = {}  # 当前持仓 {code: weight}
        self._cash: float = config.initial_capital
        self._position_history: List[Dict] = []

    # ======================== 主回测流程 ========================

    def run(
        self,
        price_data: Dict[str, pd.DataFrame],
        signal_func,
    ) -> BacktestResult:
        """
        执行回测

        Args:
            price_data: 价格数据 {code: DataFrame with columns [date, close]}
            signal_func: 信号生成函数
                        签名为 func(date: str, price_data: dict) -> List[str]
                        返回当期的选股代码列表

        Returns:
            BacktestResult: 回测结果
        """
        logger.info("=" * 50)
        logger.info(
            f"开始回测: {self.config.start_date} ~ {self.config.end_date}"
        )
        logger.info(
            f"调仓频率: {self.config.rebalance_freq}, "
            f"最大持仓: {self.config.max_positions}"
        )

        # 获取交易日历
        trading_dates = self._get_trading_dates(price_data)
        if not trading_dates:
            logger.error("没有可用的交易日数据")
            return BacktestResult()

        # 筛选回测区间内的交易日
        trading_dates = [
            d for d in trading_dates
            if self.config.start_date <= d <= self.config.end_date
        ]
        logger.info(f"回测区间交易日数: {len(trading_dates)}")

        # 确定调仓日期
        rebalance_dates = self._get_rebalance_dates(trading_dates)
        logger.info(f"调仓日期数: {len(rebalance_dates)}")

        # ===== 逐日模拟 =====
        self._cash = self.config.initial_capital
        self._nav = [self.config.initial_capital]
        self._dates = [trading_dates[0]]
        self._positions = {}
        self._position_history = []

        next_rebalance_idx = 0
        current_holdings: Dict[str, float] = {}  # {code: shares}

        for i, date in enumerate(trading_dates):
            # 检查是否需要调仓
            is_rebalance = (
                next_rebalance_idx < len(rebalance_dates)
                and date == rebalance_dates[next_rebalance_idx]
            )

            if is_rebalance:
                next_rebalance_idx += 1

                # 生成选股信号
                try:
                    selected_codes = signal_func(date, price_data)
                except Exception as e:
                    logger.warning(f"信号生成失败 {date}: {e}")
                    selected_codes = []

                # 执行调仓
                current_holdings = self._rebalance(
                    date, selected_codes, current_holdings, price_data
                )

            # 计算当日持仓市值
            portfolio_value = self._cash
            for code, shares in current_holdings.items():
                close_price = self._get_price(date, code, price_data)
                if close_price is not None:
                    portfolio_value += shares * close_price

            self._nav.append(portfolio_value)
            self._dates.append(date)

        # ===== 计算绩效指标 =====
        result = self._compute_metrics(price_data)
        result.position_history = self._position_history

        logger.info("回测完成！")
        return result

    # ======================== 调仓逻辑 ========================

    def _rebalance(
        self,
        date: str,
        selected_codes: List[str],
        current_holdings: Dict[str, float],
        price_data: Dict[str, pd.DataFrame],
    ) -> Dict[str, float]:
        """
        执行调仓操作

        Args:
            date: 当前日期
            selected_codes: 选出的股票代码列表
            current_holdings: 当前持仓 {code: shares}
            price_data: 价格数据

        Returns:
            新的持仓
        """
        # 限制持仓数量
        selected_codes = selected_codes[:self.config.max_positions]

        if not selected_codes:
            logger.debug(f"  调仓日 {date}: 无选股信号，清仓")
            # 卖出所有持仓
            for code, shares in list(current_holdings.items()):
                price = self._get_price(date, code, price_data)
                if price is not None:
                    sell_amount = shares * price * (1 - self.config.commission_rate)
                    self._cash += sell_amount
            return {}

        # ===== 计算当前总市值 =====
        current_market_value = self._cash
        for code, shares in current_holdings.items():
            price = self._get_price(date, code, price_data)
            if price is not None:
                current_market_value += shares * price

        # ===== 等权重分配 =====
        target_weight = 1.0 / len(selected_codes)
        new_holdings: Dict[str, float] = {}
        total_cost = 0.0

        for code in selected_codes:
            price = self._get_price(date, code, price_data)
            if price is None:
                continue
            # 考虑滑点（买入时价格偏高）
            buy_price = price * (1 + self.config.slippage)
            target_value = current_market_value * target_weight
            shares = target_value / buy_price
            # 扣除手续费
            cost = shares * buy_price * (1 + self.config.commission_rate)
            total_cost += cost
            new_holdings[code] = shares

        # 卖出不在新选股列表中的持仓
        for code, shares in current_holdings.items():
            if code not in selected_codes:
                price = self._get_price(date, code, price_data)
                if price is not None:
                    sell_price = price * (1 - self.config.slippage)
                    sell_amount = shares * sell_price * (1 - self.config.commission_rate)
                    self._cash += sell_amount

        # 扣除买入成本
        self._cash -= total_cost
        self._cash = max(self._cash, 0)  # 现金不为负

        # 记录持仓历史
        self._position_history.append({
            "date": date,
            "positions": list(new_holdings.keys()),
            "count": len(new_holdings),
            "cash": self._cash,
            "total_value": current_market_value,
        })

        logger.debug(
            f"  调仓日 {date}: 选中{len(selected_codes)}只, "
            f"持仓市值={current_market_value:,.0f}"
        )

        return new_holdings

    # ======================== 绩效计算 ========================

    def _compute_metrics(
        self, price_data: Dict[str, pd.DataFrame]
    ) -> BacktestResult:
        """计算各项绩效指标"""
        nav_series = pd.Series(self._nav, index=pd.to_datetime(self._dates))

        if len(nav_series) < 2:
            return BacktestResult()

        result = BacktestResult()

        # 净值序列
        result.nav_series = nav_series / nav_series.iloc[0]

        # 日收益率
        daily_returns = nav_series.pct_change().dropna()

        # 总收益率
        result.total_return = (nav_series.iloc[-1] / nav_series.iloc[0] - 1) * 100

        # 年化收益率
        years = (nav_series.index[-1] - nav_series.index[0]).days / 365.25
        if years > 0:
            result.annual_return = (
                (nav_series.iloc[-1] / nav_series.iloc[0]) ** (1 / years) - 1
            ) * 100

        # 年化波动率
        result.annual_volatility = daily_returns.std() * np.sqrt(252) * 100

        # 夏普比率
        if result.annual_volatility > 0:
            result.sharpe_ratio = (
                (result.annual_return - self.RISK_FREE_RATE * 100)
                / result.annual_volatility
            )

        # 最大回撤
        cumulative = nav_series / nav_series.cummax()
        result.max_drawdown = (cumulative.min() - 1) * 100

        # 调仓次数
        result.total_trades = len(self._position_history)

        # 胜率（调仓周期收益率>0的比例）
        if len(daily_returns) > 0:
            # 按月汇总
            monthly = daily_returns.resample("ME").apply(
                lambda x: (1 + x).prod() - 1
            )
            if len(monthly) > 0:
                result.win_rate = (monthly > 0).sum() / len(monthly) * 100

        # ===== 基准对比 =====
        benchmark_returns = self._get_benchmark_returns(price_data)
        if benchmark_returns is not None and len(benchmark_returns) > 1:
            result.benchmark_nav = benchmark_returns / benchmark_returns.iloc[0]
            result.benchmark_return = (
                benchmark_returns.iloc[-1] / benchmark_returns.iloc[0] - 1
            ) * 100
            result.excess_return = result.total_return - result.benchmark_return

            # 信息比率
            excess_daily = daily_returns - benchmark_returns.pct_change().dropna()
            if len(excess_daily) > 0 and excess_daily.std() > 0:
                result.information_ratio = (
                    excess_daily.mean() / excess_daily.std() * np.sqrt(252)
                )

        return result

    # ======================== 辅助方法 ========================

    def _get_trading_dates(
        self, price_data: Dict[str, pd.DataFrame]
    ) -> List[str]:
        """从价格数据中提取交易日历"""
        dates_set = set()
        for df in price_data.values():
            if df is not None and not df.empty:
                if "date" in df.columns:
                    dates_set.update(df["date"].astype(str).tolist())
        return sorted(dates_set)

    def _get_rebalance_dates(self, trading_dates: List[str]) -> List[str]:
        """确定调仓日期"""
        if not trading_dates:
            return []

        rebalance_dates = [trading_dates[0]]  # 首日调仓
        last_rebalance = trading_dates[0]
        rebalance_step = self.config.rebalance_days

        for date in trading_dates:
            # 计算距离上次调仓的交易日数
            idx_current = trading_dates.index(date)
            idx_last = trading_dates.index(last_rebalance)
            if idx_current - idx_last >= rebalance_step:
                rebalance_dates.append(date)
                last_rebalance = date

        return rebalance_dates

    def _get_price(
        self, date: str, code: str,
        price_data: Dict[str, pd.DataFrame]
    ) -> Optional[float]:
        """获取指定日期指定股票的收盘价"""
        df = price_data.get(code)
        if df is None or df.empty:
            return None
        if "date" not in df.columns or "close" not in df.columns:
            return None
        match = df[df["date"].astype(str) == str(date)]
        if match.empty:
            return None
        return float(match["close"].iloc[0])

    def _get_benchmark_returns(
        self, price_data: Dict[str, pd.DataFrame]
    ) -> Optional[pd.Series]:
        """获取基准指数收益率序列"""
        benchmark_code = self.config.benchmark_code
        # 尝试从price_data中找基准指数数据
        for key in [benchmark_code, f"{benchmark_code}.SH", f"{benchmark_code}.SZ"]:
            if key in price_data and price_data[key] is not None:
                df = price_data[key]
                if not df.empty and "close" in df.columns:
                    return df.set_index("date")["close"]
        return None

    # ======================== 结果输出 ========================

    @staticmethod
    def print_summary(result: BacktestResult) -> None:
        """打印回测摘要"""
        print("\n" + "=" * 60)
        print("  📊 回测绩效报告")
        print("=" * 60)

        # 收益指标
        print(f"\n  📈 收益指标:")
        print(f"     总收益率:      {result.total_return:>8.2f}%")
        print(f"     年化收益率:    {result.annual_return:>8.2f}%")
        print(f"     年化波动率:    {result.annual_volatility:>8.2f}%")
        print(f"     夏普比率:      {result.sharpe_ratio:>8.2f}")
        print(f"     最大回撤:      {result.max_drawdown:>8.2f}%")

        # 交易统计
        print(f"\n  📋 交易统计:")
        print(f"     总调仓次数:    {result.total_trades:>8}")
        print(f"     胜率:          {result.win_rate:>8.1f}%")

        # 基准对比
        print(f"\n  🎯 基准对比:")
        print(f"     策略收益率:    {result.total_return:>8.2f}%")
        print(f"     基准收益率:    {result.benchmark_return:>8.2f}%")
        print(f"     超额收益:      {result.excess_return:>8.2f}%")
        print(f"     信息比率:      {result.information_ratio:>8.2f}")

        print("\n" + "=" * 60)
