"""
全局应用配置
============
管理所有可配置参数：数据源选择、评分权重、技术指标参数、推荐阈值等。
支持从YAML文件加载配置，覆盖默认值。
"""

import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class AppConfig:
    """全局应用配置类，所有模块通过此类获取配置参数"""

    # ======================== 数据源配置 ========================
    DATA_SOURCE: str = "akshare"          # 数据源类型（akshare / tushare / baostock）
    CACHE_ENABLED: bool = True            # 是否启用数据缓存
    CACHE_DB_PATH: str = "data_cache.db"  # 缓存数据库文件路径

    # ======================== 缓存TTL（秒） ========================
    CACHE_TTL_QUOTE: int = 60             # 实时行情：60秒
    CACHE_TTL_KLINE: int = 86400          # 历史K线：1天（收盘后失效）
    CACHE_TTL_FINANCIAL: int = 604800     # 财务数据：7天
    CACHE_TTL_SENTIMENT: int = 300        # 市场情绪：5分钟
    CACHE_TTL_CAPITAL_FLOW: int = 300     # 资金流向：5分钟

    # ======================== K线数据默认参数 ========================
    DEFAULT_KLINE_PERIOD: str = "daily"   # 默认K线周期
    DEFAULT_KLINE_ADJUST: str = "qfq"     # 默认复权方式（''不复权 / 'qfq'前复权 / 'hfq'后复权）
    DEFAULT_KLINE_DAYS: int = 250         # 默认获取最近N个交易日

    # ======================== 技术指标参数 ========================
    MA_PERIODS: List[int] = field(default_factory=lambda: [5, 10, 20, 60, 120, 250])
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9
    RSI_PERIOD: int = 14
    KDJ_N: int = 9
    KDJ_K: int = 3
    KDJ_D: int = 3
    BOLL_PERIOD: int = 20
    BOLL_STD: int = 2
    VOLUME_MA_PERIOD: int = 20

    # ======================== 超买超卖阈值 ========================
    RSI_OVERBOUGHT: float = 70.0          # RSI超买线
    RSI_OVERSOLD: float = 30.0            # RSI超卖线
    KDJ_OVERBOUGHT: float = 80.0
    KDJ_OVERSOLD: float = 20.0

    # ======================== 评分权重（总和=1.0） ========================
    TECHNICAL_WEIGHT: float = 0.30        # 技术面权重
    FUNDAMENTAL_WEIGHT: float = 0.25      # 基本面权重
    CAPITAL_FLOW_WEIGHT: float = 0.20     # 资金面权重
    SENTIMENT_WEIGHT: float = 0.10        # 情绪面权重
    STRATEGY_WEIGHT: float = 0.15         # 策略面权重

    # ======================== 推荐阈值 ========================
    STRONG_BUY_THRESHOLD: int = 80        # 强烈买入线
    BUY_THRESHOLD: int = 65               # 买入线
    HOLD_THRESHOLD: int = 45              # 持有/观望线
    SELL_THRESHOLD: int = 30              # 卖出线（低于此为强烈卖出）

    # ======================== 风险参数 ========================
    VAR_CONFIDENCE: float = 0.95          # VaR置信度
    MAX_DRAWDOWN_LOOKBACK: int = 252      # 最大回撤回溯期
    VOLATILITY_WINDOW_20: int = 20        # 20日波动率窗口
    VOLATILITY_WINDOW_60: int = 60        # 60日波动率窗口

    # ======================== 网络请求 ========================
    REQUEST_TIMEOUT: int = 30             # 请求超时（秒）
    MAX_RETRIES: int = 3                  # 最大重试次数
    RETRY_DELAY: float = 1.0              # 重试初始延迟（秒），指数退避

    # ======================== 筛选默认值 ========================
    DEFAULT_SCREEN_POOL: str = "hs300"    # 默认筛选池
    DEFAULT_SCREEN_TOP: int = 20          # 默认返回前N只
    DEFAULT_RECOMMEND_TOP: int = 10       # 默认推荐数量

    # ======================== 工厂方法 ========================

    @classmethod
    def from_yaml(cls, path: str) -> "AppConfig":
        """从YAML配置文件加载配置，覆盖默认值"""
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # 过滤掉非配置字段
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从环境变量加载，支持 MEGOO_ 前缀的环境变量覆盖"""
        config = cls()
        for field_name in cls.__dataclass_fields__:
            env_key = f"MEGOO_{field_name}"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                field_type = type(getattr(config, field_name))
                if field_type == bool:
                    setattr(config, field_name, env_val.lower() in ("true", "1", "yes"))
                elif field_type == list:
                    setattr(config, field_name, env_val.split(","))
                elif field_type == float:
                    setattr(config, field_name, float(env_val))
                elif field_type == int:
                    setattr(config, field_name, int(env_val))
                else:
                    setattr(config, field_name, env_val)
        return config


# ======================== 全局默认配置实例 ========================
default_config = AppConfig()


# ======================== 建议等级映射 ========================
RECOMMENDATION_MAP = {
    "STRONG_BUY":  {"cn": "强烈买入", "color": "bright_red",    "min_score": 80},
    "BUY":         {"cn": "买入",     "color": "red",           "min_score": 65},
    "HOLD":        {"cn": "持有观望", "color": "yellow",        "min_score": 45},
    "SELL":        {"cn": "卖出",     "color": "green",         "min_score": 30},
    "STRONG_SELL": {"cn": "强烈卖出", "color": "bright_green",  "min_score": 0},
}

# ======================== 风险等级映射 ========================
RISK_LEVEL_MAP = {
    "LOW":    {"cn": "低风险", "color": "green", "max_score": 30},
    "MEDIUM": {"cn": "中风险", "color": "yellow", "max_score": 60},
    "HIGH":   {"cn": "高风险", "color": "red", "max_score": 80},
    "EXTREME": {"cn": "极高风险", "color": "bright_red", "max_score": 100},
}
