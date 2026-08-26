"""
技术因子模块
===========
采用策略模式（Strategy Pattern）实现，每个因子作为独立策略类。
所有技术因子基于K线数据计算，统一实现 calculate 接口。

因子清单（7个）：
  - 动量因子 (Momentum): 过去20日收益率
  - 反转因子 (Reversal): 过去5日收益率取负
  - 波动率因子 (Volatility): 过去20日收益率标准差（低波动高分）
  - 换手率因子 (Turnover): 成交量/流通股本（流动性衡量）
  - 量价背离因子 (VolPriceCorr): 价格变化与成交量变化的相关性
  - RSI因子: 相对强弱指标14日
  - 均线偏离因子 (MADeviation): 收盘价/20日均线-1（均值回归信号）
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import numpy as np
import pandas as pd

from analysis.indicators import (
    compute_sma, compute_rsi, compute_volatility,
    compute_price_momentum, compute_volume_ma,
)


# ═══════════════════════════════════════════════════════════════
# 策略模式：因子抽象基类
# ═══════════════════════════════════════════════════════════════

class TechnicalFactor(ABC):
    """
    技术因子抽象基类
    ================
    所有技术因子必须继承此类，实现 calculate 方法。
    策略模式使因子可插拔，便于增删改。
    """

    def __init__(self, name: str, weight: float = 1.0, direction: int = 1):
        """
        Args:
            name: 因子名称
            weight: 因子在技术大类中的权重
            direction: 因子方向（1=正向越高越好, -1=反向越低越好）
        """
        self.name = name
        self.weight = weight
        self.direction = direction
        self._raw_values: Optional[pd.Series] = None
        self._standardized: Optional[pd.Series] = None

    @abstractmethod
    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """
        计算因子原始值

        Args:
            data: 包含K线数据的字典，key为股票代码，value为K线DataFrame
                  每只股票的DataFrame至少包含: close, high, low, volume, turnover

        Returns:
            因子值序列，index为股票代码，value为因子原始值
        """
        pass

    def get_standardized(self) -> Optional[pd.Series]:
        """获取标准化后的因子值（需先调用 FactorCombiner.standardize）"""
        return self._standardized

    def describe(self) -> Dict[str, Any]:
        """返回因子的元信息"""
        return {
            "name": self.name,
            "weight": self.weight,
            "direction": self.direction,
            "type": "technical",
        }


# ═══════════════════════════════════════════════════════════════
# 具体因子实现
# ═══════════════════════════════════════════════════════════════

class Momentum20Factor(TechnicalFactor):
    """
    20日动量因子
    ============
    计算方法: 过去20日的价格收益率
    逻辑说明: 趋势跟踪，过去表现强的股票倾向于继续走强（动量效应）
    """

    def __init__(self, weight: float = 0.25):
        super().__init__(name="momentum_20", weight=weight, direction=1)

    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """计算每只股票过去20日的收益率"""
        results = {}
        for code, df in data.items():
            if df is None or df.empty or "close" not in df.columns or len(df) < 21:
                results[code] = np.nan
                continue
            close = df["close"]
            momentum = (close.iloc[-1] / close.iloc[-21] - 1) * 100
            results[code] = momentum
        self._raw_values = pd.Series(results, name="momentum_20")
        return self._raw_values


class Reversal5Factor(TechnicalFactor):
    """
    5日反转因子
    ============
    计算方法: 过去5日收益率取负值
    逻辑说明: 短期超跌反弹效应，近5日跌得多的股票倾向于反弹
    """

    def __init__(self, weight: float = 0.15):
        super().__init__(name="reversal_5", weight=weight, direction=1)
        # direction=1 是因为 calculate() 已经对收益率取负（跌得多→因子值高）
        # 不需要 direction=-1 再次取反，否则会变成动量因子

    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """计算每只股票过去5日收益率并取负"""
        results = {}
        for code, df in data.items():
            if df is None or df.empty or "close" not in df.columns or len(df) < 6:
                results[code] = np.nan
                continue
            close = df["close"]
            ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100
            results[code] = -ret_5d  # 取负值：跌得多→因子值高
        self._raw_values = pd.Series(results, name="reversal_5")
        return self._raw_values


class Volatility20Factor(TechnicalFactor):
    """
    20日波动率因子
    ==============
    计算方法: 过去20日日收益率的标准差（年化）
    逻辑说明: 低波动溢价，低波动股票风险调整后收益更高
    """

    def __init__(self, weight: float = 0.15):
        super().__init__(name="volatility_20", weight=weight, direction=-1)

    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """计算每只股票过去20日的年化波动率"""
        results = {}
        for code, df in data.items():
            if df is None or df.empty or "close" not in df.columns or len(df) < 21:
                results[code] = np.nan
                continue
            close = df["close"]
            returns = close.pct_change().dropna()
            if len(returns) < 20:
                results[code] = np.nan
                continue
            # 年化波动率
            vol = returns.iloc[-20:].std() * np.sqrt(252) * 100
            results[code] = vol
        self._raw_values = pd.Series(results, name="volatility_20")
        return self._raw_values


class Turnover20Factor(TechnicalFactor):
    """
    换手率因子
    ==========
    计算方法: 过去20日平均换手率
    逻辑说明: 衡量股票流动性，换手率适中的股票流动性好且不过度投机
    """

    def __init__(self, weight: float = 0.10):
        super().__init__(name="turnover_20", weight=weight, direction=1)

    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """计算每只股票过去20日平均换手率"""
        results = {}
        for code, df in data.items():
            if df is None or df.empty or len(df) < 21:
                results[code] = np.nan
                continue
            # 优先使用换手率列
            if "turnover" in df.columns:
                turnover = df["turnover"].iloc[-20:].mean()
            elif "volume" in df.columns:
                # 估算换手率（需要流通股本，这里用成交量替代）
                turnover = df["volume"].iloc[-20:].mean()
            else:
                results[code] = np.nan
                continue
            results[code] = turnover
        self._raw_values = pd.Series(results, name="turnover_20")
        return self._raw_values


class VolumePriceCorrFactor(TechnicalFactor):
    """
    量价背离因子
    ============
    计算方法: 过去20日价格变化与成交量变化的相关系数
    逻辑说明: 量价配合度——量价齐升表明趋势健康，量价背离预示反转风险
    """

    def __init__(self, weight: float = 0.10):
        super().__init__(name="volume_price_corr", weight=weight, direction=1)

    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """计算每只股票过去20日的量价相关系数"""
        results = {}
        for code, df in data.items():
            if df is None or df.empty or len(df) < 21:
                results[code] = np.nan
                continue
            if "close" not in df.columns or "volume" not in df.columns:
                results[code] = np.nan
                continue
            recent = df.iloc[-20:]
            price_change = recent["close"].pct_change().dropna()
            volume_change = recent["volume"].pct_change().dropna()
            # 对齐索引
            common_idx = price_change.index.intersection(volume_change.index)
            if len(common_idx) < 5:
                results[code] = np.nan
                continue
            corr = price_change[common_idx].corr(volume_change[common_idx])
            # 相关系数可能为NaN
            results[code] = corr if not pd.isna(corr) else 0.0
        self._raw_values = pd.Series(results, name="volume_price_corr")
        return self._raw_values


class RSIFactor(TechnicalFactor):
    """
    RSI因子（14日）
    ===============
    计算方法: 14日相对强弱指标
    逻辑说明: 均值回归——高RSI（超买）倾向回调，低RSI（超卖）倾向反弹
    direction=-1 表示低RSI得分更高
    """

    def __init__(self, weight: float = 0.10, period: int = 14):
        super().__init__(name=f"rsi_{period}", weight=weight, direction=-1)
        self.period = period

    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """计算每只股票的RSI值"""
        results = {}
        for code, df in data.items():
            if df is None or df.empty or "close" not in df.columns or len(df) < self.period + 1:
                results[code] = np.nan
                continue
            close = df["close"]
            rsi = compute_rsi(close, self.period)
            results[code] = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
        self._raw_values = pd.Series(results, name=f"rsi_{self.period}")
        return self._raw_values


class MADeviationFactor(TechnicalFactor):
    """
    均线偏离因子
    ============
    计算方法: (收盘价 / 20日均线) - 1
    逻辑说明: 均值回归信号——股价高于均线倾向回归（高估），低于均线倾向反弹（低估）
    direction=-1 表示低于均线的股票得分更高
    """

    def __init__(self, weight: float = 0.15, ma_period: int = 20):
        super().__init__(name=f"ma_deviation_{ma_period}", weight=weight, direction=-1)
        self.ma_period = ma_period

    def calculate(self, data: Dict[str, pd.DataFrame]) -> pd.Series:
        """计算每只股票的均线偏离度"""
        results = {}
        for code, df in data.items():
            if df is None or df.empty or "close" not in df.columns or len(df) < self.ma_period + 1:
                results[code] = np.nan
                continue
            close = df["close"]
            ma = compute_sma(close, self.ma_period)
            if pd.isna(ma.iloc[-1]):
                results[code] = np.nan
                continue
            deviation = (close.iloc[-1] / ma.iloc[-1] - 1) * 100
            results[code] = deviation
        self._raw_values = pd.Series(results, name=f"ma_deviation_{self.ma_period}")
        return self._raw_values


# ═══════════════════════════════════════════════════════════════
# 因子注册表（工厂模式）
# ═══════════════════════════════════════════════════════════════

class TechnicalFactorRegistry:
    """
    技术因子注册表
    ==============
    管理所有技术因子实例，支持按配置启用/禁用。
    """

    # 内置因子类映射
    _factor_classes: Dict[str, type] = {
        "momentum_20": Momentum20Factor,
        "reversal_5": Reversal5Factor,
        "volatility_20": Volatility20Factor,
        "turnover_20": Turnover20Factor,
        "volume_price_corr": VolumePriceCorrFactor,
        "rsi_14": RSIFactor,
        "ma_deviation": MADeviationFactor,
    }

    @classmethod
    def build_from_config(cls, config: dict) -> List[TechnicalFactor]:
        """
        根据配置创建启用的因子实例列表

        Args:
            config: 来自 config.yaml 的 technical_factors 字典

        Returns:
            启用的因子实例列表
        """
        factors = []
        for name, factor_config in config.items():
            if not factor_config.get("enabled", True):
                continue
            factor_cls = cls._factor_classes.get(name)
            if factor_cls is None:
                continue
            weight = factor_config.get("weight", 1.0)
            # 对于有特殊参数的因子，传入period等参数
            if name == "rsi_14":
                factor = factor_cls(weight=weight, period=14)
            elif name == "ma_deviation":
                factor = factor_cls(weight=weight, ma_period=20)
            else:
                factor = factor_cls(weight=weight)
            # 确保 factor.name 与配置键名一致（某些因子如 MADeviationFactor 的 __init__ 可能设置不同名字）
            factor.name = name
            factors.append(factor)
        return factors

    @classmethod
    def register(cls, name: str, factor_cls: type) -> None:
        """注册自定义技术因子"""
        cls._factor_classes[name] = factor_cls

    @classmethod
    def list_available(cls) -> List[str]:
        """列出所有可用因子名称"""
        return list(cls._factor_classes.keys())
