"""
基本面因子模块
=============
采用策略模式（Strategy Pattern）实现，每个基本面因子作为独立策略类。
所有基本面因子基于财务数据计算，统一实现 calculate 接口。

因子清单（7个）：
  - PE因子: 市盈率（取负，低PE高分）
  - PB因子: 市净率（取负，低PB高分）
  - ROE因子: 净资产收益率（高ROE高分）
  - 营收增长率: 营业收入同比增长率
  - 净利润增长率: 净利润同比增长率
  - 资产负债率因子: 总负债/总资产（取负，低负债高分）
  - 毛利率因子: 毛利润/营业收入（高毛利率高分）
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# 策略模式：基本面因子抽象基类
# ═══════════════════════════════════════════════════════════════

class FundamentalFactor(ABC):
    """
    基本面因子抽象基类
    ==================
    所有基本面因子必须继承此类，实现 calculate 方法。
    使用策略模式使因子可插拔，便于增删改。
    """

    def __init__(self, name: str, weight: float = 1.0, direction: int = 1):
        """
        Args:
            name: 因子名称
            weight: 因子在基本面大类中的权重
            direction: 因子方向（1=正向越高越好, -1=反向越低越好）
        """
        self.name = name
        self.weight = weight
        self.direction = direction
        self._raw_values: Optional[pd.Series] = None
        self._standardized: Optional[pd.Series] = None

    @abstractmethod
    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """
        计算因子原始值

        Args:
            data: 包含财务指标的字典
                  key为股票代码
                  value为财务指标字典，包含: pe, pb, roe, revenue_growth,
                       profit_growth, debt_ratio, gross_margin 等

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
            "type": "fundamental",
        }


# ═══════════════════════════════════════════════════════════════
# 具体因子实现
# ═══════════════════════════════════════════════════════════════

class PEFactor(FundamentalFactor):
    """
    市盈率因子（PE）
    ================
    计算方法: 市盈率取负值
    逻辑说明: 低PE表示估值便宜，取负使得低PE对应高分
    """

    def __init__(self, weight: float = 0.20):
        super().__init__(name="pe", weight=weight, direction=-1)

    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """计算PE因子值 = -PE"""
        results = {}
        for code, metrics in data.items():
            pe = metrics.get("pe")
            if pe is None or pe <= 0:
                results[code] = np.nan
                continue
            results[code] = -pe  # 取负：低PE→高分
        self._raw_values = pd.Series(results, name="pe")
        return self._raw_values


class PBFactor(FundamentalFactor):
    """
    市净率因子（PB）
    ================
    计算方法: 市净率取负值
    逻辑说明: 低PB表示估值便宜，尤其适合银行/周期股
    """

    def __init__(self, weight: float = 0.15):
        super().__init__(name="pb", weight=weight, direction=-1)

    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """计算PB因子值 = -PB"""
        results = {}
        for code, metrics in data.items():
            pb = metrics.get("pb")
            if pb is None or pb <= 0:
                results[code] = np.nan
                continue
            results[code] = -pb  # 取负：低PB→高分
        self._raw_values = pd.Series(results, name="pb")
        return self._raw_values


class ROEFactor(FundamentalFactor):
    """
    ROE因子（净资产收益率）
    =======================
    计算方法: ROE原始值
    逻辑说明: 高ROE表示盈利能力强（巴菲特核心指标），ROE>15%为优秀
    """

    def __init__(self, weight: float = 0.20):
        super().__init__(name="roe", weight=weight, direction=1)

    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """计算ROE因子值"""
        results = {}
        for code, metrics in data.items():
            roe = metrics.get("roe")
            if roe is None:
                results[code] = np.nan
                continue
            results[code] = roe
        self._raw_values = pd.Series(results, name="roe")
        return self._raw_values


class RevenueGrowthFactor(FundamentalFactor):
    """
    营收增长率因子
    ==============
    计算方法: 营业收入同比增长率（%）
    逻辑说明: 营收增长表明业务扩张，高增长公司未来发展空间大
    """

    def __init__(self, weight: float = 0.15):
        super().__init__(name="revenue_growth", weight=weight, direction=1)

    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """计算营收增长率因子值"""
        results = {}
        for code, metrics in data.items():
            growth = metrics.get("revenue_growth")
            if growth is None:
                results[code] = np.nan
                continue
            results[code] = growth
        self._raw_values = pd.Series(results, name="revenue_growth")
        return self._raw_values


class ProfitGrowthFactor(FundamentalFactor):
    """
    净利润增长率因子
    ================
    计算方法: 净利润同比增长率（%）
    逻辑说明: 利润增长是股价长期上涨的核心驱动力
    """

    def __init__(self, weight: float = 0.15):
        super().__init__(name="profit_growth", weight=weight, direction=1)

    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """计算净利润增长率因子值"""
        results = {}
        for code, metrics in data.items():
            growth = metrics.get("profit_growth")
            if growth is None:
                results[code] = np.nan
                continue
            results[code] = growth
        self._raw_values = pd.Series(results, name="profit_growth")
        return self._raw_values


class DebtRatioFactor(FundamentalFactor):
    """
    资产负债率因子
    ==============
    计算方法: 资产负债率取负值
    逻辑说明: 低负债率表示偿债风险小，财务结构健康
    """

    def __init__(self, weight: float = 0.10):
        super().__init__(name="debt_ratio", weight=weight, direction=-1)

    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """计算资产负债率因子值 = -资产负债率"""
        results = {}
        for code, metrics in data.items():
            debt = metrics.get("debt_ratio")
            if debt is None:
                results[code] = np.nan
                continue
            results[code] = -debt  # 取负：低负债→高分
        self._raw_values = pd.Series(results, name="debt_ratio")
        return self._raw_values


class GrossMarginFactor(FundamentalFactor):
    """
    毛利率因子
    ==========
    计算方法: 毛利率原始值（%）
    逻辑说明: 高毛利率表示产品竞争力强（护城河），盈利质量好
    """

    def __init__(self, weight: float = 0.05):
        super().__init__(name="gross_margin", weight=weight, direction=1)

    def calculate(self, data: Dict[str, Dict[str, Any]]) -> pd.Series:
        """计算毛利率因子值"""
        results = {}
        for code, metrics in data.items():
            margin = metrics.get("gross_margin")
            if margin is None:
                results[code] = np.nan
                continue
            results[code] = margin
        self._raw_values = pd.Series(results, name="gross_margin")
        return self._raw_values


# ═══════════════════════════════════════════════════════════════
# 因子注册表（工厂模式）
# ═══════════════════════════════════════════════════════════════

class FundamentalFactorRegistry:
    """
    基本面因子注册表
    ================
    管理所有基本面因子实例，支持按配置启用/禁用。
    """

    # 内置因子类映射
    _factor_classes: Dict[str, type] = {
        "pe": PEFactor,
        "pb": PBFactor,
        "roe": ROEFactor,
        "revenue_growth": RevenueGrowthFactor,
        "profit_growth": ProfitGrowthFactor,
        "debt_ratio": DebtRatioFactor,
        "gross_margin": GrossMarginFactor,
    }

    @classmethod
    def build_from_config(cls, config: dict) -> List[FundamentalFactor]:
        """
        根据配置创建启用的因子实例列表

        Args:
            config: 来自 config.yaml 的 fundamental_factors 字典

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
            factor = factor_cls(weight=weight)
            factors.append(factor)
        return factors

    @classmethod
    def register(cls, name: str, factor_cls: type) -> None:
        """注册自定义基本面因子"""
        cls._factor_classes[name] = factor_cls

    @classmethod
    def list_available(cls) -> List[str]:
        """列出所有可用因子名称"""
        return list(cls._factor_classes.keys())
