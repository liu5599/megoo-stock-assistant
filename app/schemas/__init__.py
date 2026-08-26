"""
API 请求/响应 Pydantic 模型
===========================
为所有 API 端点提供输入验证和响应序列化。
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# 股票相关
# ═══════════════════════════════════════════════════════════════

class StockSearchResult(BaseModel):
    """股票搜索结果"""
    code: str
    name: str


class StockSearchResponse(BaseModel):
    """搜索响应"""
    results: List[StockSearchResult]
    total: int


class KLinePoint(BaseModel):
    """单根K线数据点"""
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float


class StockKLineResponse(BaseModel):
    """K线数据响应"""
    code: str
    name: str
    klines: List[KLinePoint]
    indicators: Optional[Dict[str, Any]] = None


class BuyScoreModel(BaseModel):
    """买入评分"""
    total: float
    technical: float
    fundamental: float
    risk_adjusted: float
    rating: str
    confidence: str


class RiskModel(BaseModel):
    """风险评估"""
    overall_risk_level: str
    overall_risk_score: float
    stop_loss_price: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_price: Optional[float] = None
    take_profit_pct: Optional[float] = None
    max_drawdown_pct: float = 0
    volatility_pct: float = 0
    position_pct: Optional[float] = None
    warnings: List[str] = []


class StockAnalysisResponse(BaseModel):
    """单只股票完整分析响应"""
    code: str
    name: str
    price: float
    buy_score: Optional[BuyScoreModel] = None
    risk: Optional[RiskModel] = None
    technical_summary: Optional[Dict] = None
    fundamental_summary: Optional[Dict] = None
    recommendation: str = ""
    action_summary: str = ""
    generated_at: str = ""


class StockFinancialResponse(BaseModel):
    """财务数据响应"""
    code: str
    name: str
    pe: Optional[float] = None
    pb: Optional[float] = None
    roe: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_growth: Optional[float] = None
    debt_ratio: Optional[float] = None
    gross_margin: Optional[float] = None
    dividend_yield: Optional[float] = None


# ═══════════════════════════════════════════════════════════════
# 排名相关
# ═══════════════════════════════════════════════════════════════

class RankingRequest(BaseModel):
    """排名请求参数"""
    pool: str = Field(default="hs300", description="股票池: hs300 / zz500 / sz50 / all")
    top_n: int = Field(default=20, ge=1, le=100, description="返回前N只")
    tech_weight: float = Field(default=0.40, ge=0, le=1, description="技术面权重")
    fund_weight: float = Field(default=0.60, ge=0, le=1, description="基本面权重")
    filters: Optional[Dict[str, Any]] = None


class RankingItem(BaseModel):
    """单个排名条目"""
    rank: int
    code: str
    name: str
    price: float
    total_score: float
    risk_adjusted_score: float
    tech_score: float
    fund_score: float
    risk_level: str
    stop_loss: float = 0
    stop_loss_pct: float = 0
    take_profit: float = 0
    take_profit_pct: float = 0
    position_pct: float = 0


class RankingResponse(BaseModel):
    """排名响应"""
    results: List[RankingItem]
    total: int
    pool_name: str = ""
    generated_at: str = ""


class TaskStatusResponse(BaseModel):
    """异步任务状态"""
    task_id: str
    status: str
    progress: float = 0.0
    message: str = ""
    completed_at: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# 回测相关
# ═══════════════════════════════════════════════════════════════

class BacktestRequest(BaseModel):
    """回测请求参数"""
    strategy: str = Field(default="comprehensive")
    start_date: str = Field(default="20250101", description="YYYYMMDD")
    end_date: str = Field(default="20260630", description="YYYYMMDD")
    pool: str = Field(default="hs300")
    initial_capital: float = Field(default=1000000, ge=10000)
    rebalance_freq: str = Field(default="monthly")


class BacktestMetrics(BaseModel):
    """回测绩效指标"""
    total_return: float = 0.0
    annual_return: float = 0.0
    annual_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    information_ratio: float = 0.0
    total_trades: int = 0


class BacktestResponse(BaseModel):
    """回测结果响应"""
    task_id: str
    status: str
    metrics: Optional[BacktestMetrics] = None
    nav_series: Optional[List[Dict]] = None


# ═══════════════════════════════════════════════════════════════
# 市场相关
# ═══════════════════════════════════════════════════════════════

class MarketOverviewResponse(BaseModel):
    """市场概览响应"""
    indices: List[Dict[str, Any]] = []
    advance_count: int = 0
    decline_count: int = 0
    flat_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    market_heat: float = 50.0
    north_total_inflow: Optional[float] = None
    hot_sectors: List[Dict[str, Any]] = []
    generated_at: str = ""


# ═══════════════════════════════════════════════════════════════
# 自选股相关
# ═══════════════════════════════════════════════════════════════

class WatchlistItem(BaseModel):
    """自选股条目"""
    code: str
    name: str
    price: Optional[float] = None
    change_pct: Optional[float] = None


class WatchlistResponse(BaseModel):
    """自选股列表响应"""
    stocks: List[WatchlistItem]
    count: int
    updated_at: str = ""


class WatchlistAddRequest(BaseModel):
    """添加自选股请求"""
    codes: str = Field(..., description="逗号分隔的股票代码")
    names: str = Field(default="")


class WatchlistRemoveRequest(BaseModel):
    """移除自选股请求"""
    codes: str = Field(..., description="逗号分隔的股票代码")


# ═══════════════════════════════════════════════════════════════
# 系统相关
# ═══════════════════════════════════════════════════════════════

class SystemStatusResponse(BaseModel):
    """系统状态响应"""
    status: str = "ok"
    version: str = "2.0.0"
    data_source: str = ""
    cache_size: int = 0
    uptime_seconds: float = 0


class ErrorResponse(BaseModel):
    """统一错误响应"""
    error: str
    detail: Optional[str] = None
    status_code: int = 500
