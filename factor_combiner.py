"""
多因子合成与打分模块
===================
负责因子标准化、异常值处理、加权合成和综合排序。

核心流程：
  1. 因子标准化（Rank / Z-Score / MinMax）
  2. 异常值处理（Winsorize / Clip）
  3. 缺失值处理（行业中位数填充 / 剔除）
  4. 因子加权合成（大类内加权 → 大类间加权）
  5. 综合评分排序

设计模式：
  - 策略模式：标准化方法可插拔
  - 模板方法：处理流程固定，具体步骤可定制
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple, Any
import numpy as np
import pandas as pd

from factor_technical import TechnicalFactor
from factor_fundamental import FundamentalFactor
from utils.logger import logger


# ═══════════════════════════════════════════════════════════════
# 标准化策略
# ═══════════════════════════════════════════════════════════════

class Normalizer(ABC):
    """标准化策略抽象基类"""

    @abstractmethod
    def normalize(self, series: pd.Series) -> pd.Series:
        """
        对因子值进行标准化

        Args:
            series: 原始因子值序列

        Returns:
            标准化后的因子值序列（0-100或标准正态分布）
        """
        pass


class RankNormalizer(Normalizer):
    """
    Rank标准化（分位数法）
    ======================
    将因子值转换为0-100的分位数排名。
    优点：对异常值不敏感，分布均匀。
    适用：A股因子分布通常有肥尾特征。
    """

    def normalize(self, series: pd.Series) -> pd.Series:
        """按分位数排名标准化"""
        valid = series.dropna()
        if len(valid) == 0:
            return pd.Series(np.nan, index=series.index)
        # 计算百分位排名
        ranks = valid.rank(pct=True) * 100
        return ranks.reindex(series.index)


class ZScoreNormalizer(Normalizer):
    """
    Z-Score标准化
    ==============
    将因子值转换为均值0标准差1的正态分布。
    优点：保留原始分布形态。
    缺点：对异常值敏感。
    """

    def normalize(self, series: pd.Series) -> pd.Series:
        """Z-Score标准化后映射到0-100"""
        valid = series.dropna()
        if len(valid) < 2:
            return pd.Series(np.nan, index=series.index)
        mean = valid.mean()
        std = valid.std()
        if std == 0:
            return pd.Series(50.0, index=series.index)
        z_scores = (series - mean) / std
        # 映射到0-100（sigmoid变换）
        normalized = 100 / (1 + np.exp(-z_scores))
        return normalized


class MinMaxNormalizer(Normalizer):
    """
    Min-Max标准化
    ==============
    将因子值线性映射到0-100区间。
    优点：简单直观。
    缺点：对异常值极度敏感。
    """

    def normalize(self, series: pd.Series) -> pd.Series:
        """Min-Max标准化到0-100"""
        valid = series.dropna()
        if len(valid) < 2:
            return pd.Series(np.nan, index=series.index)
        vmin, vmax = valid.min(), valid.max()
        if vmax == vmin:
            return pd.Series(50.0, index=series.index)
        return ((series - vmin) / (vmax - vmin)) * 100


# ═══════════════════════════════════════════════════════════════
# 多因子合成器
# ═══════════════════════════════════════════════════════════════

class FactorCombiner:
    """
    多因子合成与打分引擎
    ====================
    负责将多个技术因子和基本面因子合成为综合评分。

    使用示例:
        >>> combiner = FactorCombiner(config)
        >>> combiner.set_factors(tech_factors, fund_factors)
        >>> scores = combiner.compute(kline_data, financial_data)
        >>> top20 = combiner.get_top_n(20)
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 来自 config.yaml 的完整配置字典
        """
        strategy_cfg = config.get("strategy", {})
        self.technical_weight = strategy_cfg.get("technical_weight", 0.40)
        self.fundamental_weight = strategy_cfg.get("fundamental_weight", 0.60)
        self.top_n = strategy_cfg.get("top_n", 20)

        # 标准化方法
        norm_method = strategy_cfg.get("normalization", "rank")
        self.normalizer = self._get_normalizer(norm_method)

        # 异常值处理
        self.outlier_method = strategy_cfg.get("outlier_method", "winsorize")
        self.outlier_percentile = strategy_cfg.get("outlier_percentile", 0.01)

        # 因子列表
        self._tech_factors: List[TechnicalFactor] = []
        self._fund_factors: List[FundamentalFactor] = []

        # 结果缓存
        self._tech_scores: Optional[pd.Series] = None
        self._fund_scores: Optional[pd.Series] = None
        self._combined_scores: Optional[pd.Series] = None
        self._all_factor_scores: Optional[pd.DataFrame] = None

    # ======================== 因子设置 ========================

    def set_factors(self, tech_factors: List[TechnicalFactor],
                    fund_factors: List[FundamentalFactor]) -> None:
        """
        设置要使用的因子列表

        Args:
            tech_factors: 技术因子实例列表
            fund_factors: 基本面因子实例列表
        """
        self._tech_factors = tech_factors
        self._fund_factors = fund_factors
        logger.info(
            f"因子组合器已就绪: "
            f"技术因子{len(tech_factors)}个, 基本面因子{len(fund_factors)}个"
        )

    # ======================== 核心计算流程 ========================

    def compute(
        self,
        kline_data: Dict[str, pd.DataFrame],
        financial_data: Dict[str, Dict[str, Any]],
    ) -> pd.DataFrame:
        """
        执行完整的多因子计算与合成流程

        步骤：
          1. 计算各因子原始值
          2. 异常值处理
          3. 缺失值填充
          4. 标准化
          5. 大类内加权合成
          6. 大类间加权合成
          7. 排序输出

        Args:
            kline_data: K线数据字典 {code: DataFrame}
            financial_data: 财务数据字典 {code: {指标名: 值}}

        Returns:
            综合评分DataFrame，包含每个因子的标准化得分和总分，按总分降序
        """
        logger.info("=" * 50)
        logger.info("开始多因子计算流程...")

        # Step 1: 计算各因子原始值
        logger.info("Step 1/5: 计算因子原始值...")
        tech_raw = self._compute_technical_raw(kline_data)
        fund_raw = self._compute_fundamental_raw(financial_data)

        # Step 2: 异常值处理
        logger.info("Step 2/5: 异常值处理...")
        tech_processed = self._handle_outliers(tech_raw)
        fund_processed = self._handle_outliers(fund_raw)

        # Step 3: 缺失值处理
        logger.info("Step 3/5: 缺失值处理...")
        tech_processed = self._handle_missing(tech_processed)
        fund_processed = self._handle_missing(fund_processed)

        # Step 4: 标准化 + 方向调整 + 大类内加权
        logger.info("Step 4/5: 标准化与加权合成...")
        self._tech_scores = self._synthesize_category(
            tech_processed, self._tech_factors, "技术面"
        )
        self._fund_scores = self._synthesize_category(
            fund_processed, self._fund_factors, "基本面"
        )

        # Step 5: 大类间加权合成
        logger.info("Step 5/5: 综合评分计算...")
        self._combined_scores = self._combine_categories()

        # 收集所有因子得分用于分析
        self._collect_all_scores(tech_processed, fund_processed)

        logger.info(
            f"多因子计算完成: {len(self._combined_scores.dropna())}只股票有效评分"
        )
        return self.get_results()

    # ======================== 内部步骤方法 ========================

    def _compute_technical_raw(
        self, kline_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """计算所有技术因子原始值"""
        factor_values = {}
        for factor in self._tech_factors:
            raw = factor.calculate(kline_data)
            factor_values[factor.name] = raw
            logger.debug(f"  技术因子 [{factor.name}]: "
                        f"{raw.dropna().count()}只有效值")
        return pd.DataFrame(factor_values)

    def _compute_fundamental_raw(
        self, financial_data: Dict[str, Dict[str, Any]]
    ) -> pd.DataFrame:
        """计算所有基本面因子原始值"""
        factor_values = {}
        for factor in self._fund_factors:
            raw = factor.calculate(financial_data)
            factor_values[factor.name] = raw
            logger.debug(f"  基本面因子 [{factor.name}]: "
                        f"{raw.dropna().count()}只有效值")
        return pd.DataFrame(factor_values)

    def _handle_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        异常值处理

        支持方法：
          - winsorize: 缩尾处理（将超出分位数的值替换为分位数值）
          - clip: 截断（按固定阈值截断）
          - none: 不处理
        """
        if self.outlier_method == "none" or df.empty:
            return df

        result = df.copy()
        lower_pct = self.outlier_percentile
        upper_pct = 1 - self.outlier_percentile

        for col in result.columns:
            series = result[col].dropna()
            if len(series) < 5:
                continue
            lower = series.quantile(lower_pct)
            upper = series.quantile(upper_pct)
            result[col] = result[col].clip(lower, upper)

        return result

    def _handle_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        缺失值处理
        策略：用该列中位数填充（比均值更稳健）
        """
        if df.empty:
            return df
        result = df.copy()
        for col in result.columns:
            median_val = result[col].median()
            if not pd.isna(median_val):
                result[col] = result[col].fillna(median_val)
            else:
                result[col] = result[col].fillna(0.0)
        return result

    def _synthesize_category(
        self,
        raw_df: pd.DataFrame,
        factors: list,
        category_name: str,
    ) -> pd.Series:
        """
        大类内因子合成：
          1. 各因子标准化
          2. 方向调整（direction=-1则取反）
          3. 加权求和

        Args:
            raw_df: 原始因子值DataFrame（已处理异常值和缺失值）
            factors: 因子实例列表
            category_name: 大类名称

        Returns:
            大类综合得分序列
        """
        if raw_df.empty or not factors:
            return pd.Series(dtype=float)

        scores = pd.DataFrame(index=raw_df.index)
        total_weight = 0.0

        for factor in factors:
            col_name = factor.name
            if col_name not in raw_df.columns:
                logger.warning(f"因子 [{col_name}] 不在数据中，跳过")
                continue

            raw = raw_df[col_name]

            # 标准化到0-100
            normalized = self.normalizer.normalize(raw)

            # 方向调整：direction=-1时取反（100 - score）
            if factor.direction == -1:
                normalized = 100 - normalized

            # 存回因子对象（供后续查询）
            factor._standardized = normalized

            scores[col_name] = normalized * factor.weight
            total_weight += factor.weight

        # 加权求和（归一化权重）
        if total_weight > 0:
            result = scores.sum(axis=1) / total_weight
        else:
            result = pd.Series(50.0, index=raw_df.index)

        logger.info(f"  {category_name}合成完成: "
                    f"{result.dropna().count()}只有效评分, "
                    f"均值={result.mean():.1f}")

        return result

    def _combine_categories(self) -> pd.Series:
        """大类间加权合成：技术面 × W_tech + 基本面 × W_fund"""
        combined = pd.Series(0.0, index=self._all_codes_index())

        if self._tech_scores is not None:
            combined = combined.add(
                self._tech_scores.fillna(50.0) * self.technical_weight,
                fill_value=0
            )

        if self._fund_scores is not None:
            combined = combined.add(
                self._fund_scores.fillna(50.0) * self.fundamental_weight,
                fill_value=0
            )

        return combined

    def _all_codes_index(self) -> pd.Index:
        """获取所有涉及到的股票代码索引"""
        indices = []
        if self._tech_scores is not None:
            indices.append(self._tech_scores.index)
        if self._fund_scores is not None:
            indices.append(self._fund_scores.index)
        if not indices:
            return pd.Index([])
        return indices[0].union(indices[1]) if len(indices) > 1 else indices[0]

    def _collect_all_scores(self, tech_raw: pd.DataFrame,
                             fund_raw: pd.DataFrame) -> None:
        """收集所有因子标准化得分到DataFrame"""
        dfs = []
        for factor in self._tech_factors + self._fund_factors:
            std = factor.get_standardized()
            if std is not None:
                dfs.append(std.rename(factor.name))
        if dfs:
            self._all_factor_scores = pd.concat(dfs, axis=1)

    # ======================== 结果输出 ========================

    def get_results(self) -> pd.DataFrame:
        """
        获取最终排序结果

        Returns:
            DataFrame with columns:
              - code: 股票代码
              - total_score: 综合得分
              - tech_score: 技术面得分
              - fund_score: 基本面得分
              - rank: 排名
        """
        if self._combined_scores is None:
            return pd.DataFrame()

        results = pd.DataFrame({
            "code": self._combined_scores.index,
            "total_score": self._combined_scores.values,
        })

        if self._tech_scores is not None:
            results["tech_score"] = results["code"].map(self._tech_scores)
        else:
            results["tech_score"] = np.nan

        if self._fund_scores is not None:
            results["fund_score"] = results["code"].map(self._fund_scores)
        else:
            results["fund_score"] = np.nan

        # 添加各因子得分
        if self._all_factor_scores is not None:
            for col in self._all_factor_scores.columns:
                results[f"factor_{col}"] = results["code"].map(
                    self._all_factor_scores[col]
                )

        # 排序
        results = results.sort_values("total_score", ascending=False)
        results = results.dropna(subset=["total_score"])
        results["rank"] = range(1, len(results) + 1)
        results = results.reset_index(drop=True)

        # 四舍五入
        for col in results.columns:
            if results[col].dtype == float:
                results[col] = results[col].round(2)

        return results

    def get_top_n(self, n: int = None) -> pd.DataFrame:
        """
        获取Top N推荐

        Args:
            n: 返回前N只，默认使用配置值

        Returns:
            Top N评分DataFrame
        """
        if n is None:
            n = self.top_n
        results = self.get_results()
        return results.head(n)

    def get_factor_exposure(self) -> Optional[pd.DataFrame]:
        """获取各因子的暴露矩阵（用于分析因子贡献）"""
        return self._all_factor_scores

    # ======================== 工具方法 ========================

    @staticmethod
    def _get_normalizer(method: str) -> Normalizer:
        """根据配置获取标准化器"""
        normalizers = {
            "rank": RankNormalizer(),
            "zscore": ZScoreNormalizer(),
            "minmax": MinMaxNormalizer(),
        }
        return normalizers.get(method.lower(), RankNormalizer())

    def get_summary(self) -> Dict[str, Any]:
        """获取计算摘要信息"""
        results = self.get_results()
        return {
            "total_stocks": len(results),
            "mean_score": results["total_score"].mean() if not results.empty else 0,
            "std_score": results["total_score"].std() if not results.empty else 0,
            "max_score": results["total_score"].max() if not results.empty else 0,
            "min_score": results["total_score"].min() if not results.empty else 0,
            "tech_weight": self.technical_weight,
            "fund_weight": self.fundamental_weight,
            "tech_factors": [f.name for f in self._tech_factors],
            "fund_factors": [f.name for f in self._fund_factors],
            "normalization": type(self.normalizer).__name__,
        }
