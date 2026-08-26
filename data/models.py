"""
数据模型定义
===========
系统中所有核心数据结构的dataclass定义。
所有模型支持序列化（asdict），作为模块间数据传递的契约。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List
import pandas as pd


# ======================== 行情数据模型 ========================

@dataclass
class StockQuote:
    """单只股票实时行情"""
    code: str                               # 股票代码，如 '000001'
    name: str                               # 股票名称，如 '平安银行'
    price: float                            # 最新价
    change_pct: float                       # 涨跌幅（%）
    change_amount: float                    # 涨跌额
    volume: float                           # 成交量（手）
    amount: float                           # 成交额（元）
    turnover: float                         # 换手率（%）
    amplitude: float                        # 振幅（%）
    high: float                             # 最高价
    low: float                              # 最低价
    open: float                             # 开盘价
    pre_close: float                        # 前收盘价
    pe_dynamic: Optional[float] = None      # 动态市盈率
    pb: Optional[float] = None              # 市净率
    total_market_cap: Optional[float] = None  # 总市值（元）
    circulating_market_cap: Optional[float] = None  # 流通市值（元）
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class KLineData:
    """历史K线数据包装器"""
    code: str
    name: str = ""
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    # DataFrame列: date, open, close, high, low, volume, amount, amplitude, change_pct, change_amount, turnover
    period: str = "daily"                   # 'daily' | 'weekly' | 'monthly'
    adjust: str = "qfq"                     # '' | 'qfq'前复权 | 'hfq'后复权

    @property
    def latest_close(self) -> Optional[float]:
        """最新收盘价"""
        if self.df.empty:
            return None
        return float(self.df["close"].iloc[-1])

    @property
    def latest_volume(self) -> Optional[float]:
        """最新成交量"""
        if self.df.empty:
            return None
        return float(self.df["volume"].iloc[-1])

    @property
    def data_count(self) -> int:
        """数据条数"""
        return len(self.df)


# ======================== 财务数据模型 ========================

@dataclass
class FinancialData:
    """财务数据聚合"""
    code: str
    name: str = ""
    roe: Optional[float] = None             # 净资产收益率（%）
    pe: Optional[float] = None              # 市盈率
    pb: Optional[float] = None              # 市净率
    revenue_growth: Optional[float] = None  # 营收同比增长率（%）
    profit_growth: Optional[float] = None   # 净利润同比增长率（%）
    gross_margin: Optional[float] = None    # 毛利率（%）
    net_margin: Optional[float] = None      # 净利率（%）
    debt_ratio: Optional[float] = None      # 资产负债率（%）
    dividend_yield: Optional[float] = None  # 股息率（%）
    total_market_cap: Optional[float] = None  # 总市值
    total_income: Optional[float] = None     # 营业总收入
    report_date: Optional[str] = None       # 报告期


# ======================== 资金流向数据模型 ========================

@dataclass
class CapitalFlowData:
    """资金流向数据"""
    code: str
    name: str = ""
    main_net_inflow: Optional[float] = None         # 主力净流入（万元）
    super_large_net_inflow: Optional[float] = None  # 超大单净流入（万元）
    large_net_inflow: Optional[float] = None        # 大单净流入（万元）
    medium_net_inflow: Optional[float] = None       # 中单净流入（万元）
    small_net_inflow: Optional[float] = None        # 小单净流入（万元）
    main_inflow_ratio: Optional[float] = None       # 主力净流入占比（%）
    north_net_inflow: Optional[float] = None        # 北向资金净流入（万元）
    north_holding_ratio: Optional[float] = None     # 北向资金持股比例（%）
    margin_balance: Optional[float] = None          # 融资余额（万元）
    margin_change: Optional[float] = None           # 融资余额变化（万元）


# ======================== 市场情绪数据模型 ========================

@dataclass
class MarketSentimentData:
    """市场情绪数据"""
    timestamp: datetime = field(default_factory=datetime.now)
    advance_count: int = 0                  # 上涨家数
    decline_count: int = 0                  # 下跌家数
    flat_count: int = 0                     # 平盘家数
    limit_up_count: int = 0                 # 涨停家数
    limit_down_count: int = 0               # 跌停家数
    market_heat_index: float = 50.0         # 市场热度指数（0-100）
    north_total_inflow: Optional[float] = None  # 北向资金总净流入（亿元）
    sector_momentum: Dict[str, float] = field(default_factory=dict)  # 板块动量
    source: str = ""                        # 数据来源标识
    estimated: bool = True                  # 是否为估算/降级数据（True=不可靠，需前端标注）


# ======================== 分析摘要模型 ========================

@dataclass
class TechnicalSummary:
    """技术面分析摘要"""
    trend_direction: str = "sideways"       # 'bull'多头 | 'bear'空头 | 'sideways'震荡
    trend_strength: float = 50.0            # 趋势强度 0-100
    ma_arrangement: str = "mixed"           # 均线排列：'bull'多头 | 'bear'空头 | 'mixed'交织
    macd_signal: str = ""                   # MACD信号：'golden_cross'金叉 | 'death_cross'死叉
    rsi_value: float = 50.0                 # RSI值
    rsi_signal: str = "neutral"             # 'overbought' | 'oversold' | 'neutral'
    kdj_signal: str = "neutral"             # KDJ信号
    bollinger_signal: str = "neutral"       # 布林带信号
    volume_signal: str = "neutral"          # 量价关系信号
    support_levels: List[float] = field(default_factory=list)   # 支撑位列表
    resistance_levels: List[float] = field(default_factory=list)  # 阻力位列表
    score: float = 50.0                     # 技术面评分 0-100


@dataclass
class FundamentalSummary:
    """基本面分析摘要"""
    valuation_level: str = "fair"           # 'undervalued'低估 | 'fair'合理 | 'overvalued'高估
    profitability_level: str = "average"    # 'excellent' | 'good' | 'average' | 'poor'
    growth_level: str = "stable"            # 'high_growth' | 'moderate' | 'stable' | 'declining'
    highlights: List[str] = field(default_factory=list)    # 亮点
    concerns: List[str] = field(default_factory=list)      # 风险点
    score: float = 50.0


@dataclass
class CapitalFlowSummary:
    """资金面分析摘要"""
    main_force_trend: str = "neutral"       # 'inflow' | 'outflow' | 'neutral'
    north_bound_trend: str = "neutral"      # 'increasing'增持 | 'decreasing'减持 | 'neutral'
    margin_trend: str = "neutral"           # 'increasing' | 'decreasing' | 'neutral'
    highlights: List[str] = field(default_factory=list)
    score: float = 50.0


@dataclass
class SentimentSummary:
    """市场情绪分析摘要"""
    market_heat: float = 50.0               # 热度指数 0-100
    breadth_signal: str = "neutral"         # 'bullish' | 'bearish' | 'neutral'
    sector_strength: str = "neutral"        # 板块强弱
    impact_on_stock: str = "neutral"        # 对个股影响：'positive' | 'negative' | 'neutral'
    score: float = 50.0


# ======================== 核心管线对象 ========================

@dataclass
class AnalysisContext:
    """
    分析上下文 —— 在分析管线中传递的核心数据对象
    聚合原始数据和分析结果，供策略和引擎使用
    """
    code: str
    name: str = ""

    # 原始数据
    quote: Optional[StockQuote] = None
    kline: Optional[KLineData] = None
    financial: Optional[FinancialData] = None
    capital_flow: Optional[CapitalFlowData] = None
    sentiment: Optional[MarketSentimentData] = None

    # 分析结果
    technical_summary: Optional[TechnicalSummary] = None
    fundamental_summary: Optional[FundamentalSummary] = None
    capital_flow_summary: Optional[CapitalFlowSummary] = None
    sentiment_summary: Optional[SentimentSummary] = None

    # 元信息
    data_completeness: float = 0.0          # 数据完整度 0.0-1.0
    analysis_timestamp: datetime = field(default_factory=datetime.now)

    def get_available_dimensions(self) -> List[str]:
        """获取有数据的分析维度"""
        dims = []
        if self.technical_summary is not None:
            dims.append("技术面")
        if self.fundamental_summary is not None:
            dims.append("基本面")
        if self.capital_flow_summary is not None:
            dims.append("资金面")
        if self.sentiment_summary is not None:
            dims.append("情绪面")
        return dims
