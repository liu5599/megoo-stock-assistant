# 🐂 megoo股票助手 v1.0

**沪深A股多因子选股框架** — 技术面与基本面兼顾的量化选股助手。

---

## 📖 框架说明

megoo股票助手是一个基于多因子模型的A股选股框架，采用**策略模式**实现可插拔的因子体系，支持技术面因子与基本面因子的灵活组合与加权评分。

### 核心特性

- ✅ **14个内置因子**：7个技术因子 + 7个基本面因子
- ✅ **策略模式**：因子可插拔，支持自定义扩展
- ✅ **多因子合成**：Rank/Z-Score/MinMax标准化，Winsorize异常值处理
- ✅ **回测引擎**：支持自定义调仓周期、手续费、滑点、基准对比
- ✅ **灵活配置**：YAML配置文件，权重可调
- ✅ **数据缓存**：Parquet本地缓存，避免重复请求

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.9+
- 依赖包见 `requirements.txt`

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行演示

```bash
# 运行完整演示流程（推荐首次使用）
python main.py demo

# 进入交互式命令行
python main.py cli

# 查看CLI帮助
python main.py --help
```

---

## 📂 项目结构

```
megoo股票助手/
│
├── main.py                     # 程序入口（演示流程 + CLI）
├── config.yaml                 # 全局YAML配置文件
├── requirements.txt            # 依赖列表
├── README.md                   # 项目说明
│
├── data/                       # 数据层
│   ├── models.py               # 数据模型（dataclass）
│   ├── fetcher.py              # 数据获取抽象基类（工厂模式）
│   ├── akshare_fetcher.py      # Akshare数据源实现
│   ├── cache.py                # SQLite + Parquet缓存引擎
│   └── stock_manager.py        # 股票列表管理与自选股
│
├── factor_technical.py         # 技术因子模块（7个因子，策略模式）
├── factor_fundamental.py       # 基本面因子模块（7个因子，策略模式）
├── factor_combiner.py          # 多因子合成与打分模块
├── backtest_engine.py          # 回测引擎
│
├── analysis/                   # 分析层
│   ├── indicators.py           # 底层指标计算（纯数学函数）
│   ├── technical.py            # 综合技术分析器
│   ├── fundamental.py          # 综合基本面分析器
│   ├── capital_flow.py         # 资金面分析器
│   └── market_sentiment.py     # 市场情绪分析器
│
├── strategy/                   # 策略层
│   ├── base_strategy.py        # 策略抽象基类
│   ├── trend_following.py      # 趋势跟踪策略
│   ├── mean_reversion.py       # 均值回归策略
│   ├── multi_factor.py         # 多因子评分模型
│   └── signal.py               # 信号生成与过滤
│
├── engine/                     # 推荐引擎层
│   ├── recommendation.py       # 核心推荐编排器
│   ├── scorer.py               # 加权评分器
│   ├── risk.py                 # 风险评估
│   └── ranking.py              # 排序筛选器
│
├── presentation/               # 展示层
│   ├── cli.py                  # Click命令行界面
│   ├── formatter.py            # Rich终端格式化
│   ├── report.py               # HTML报告生成
│   ├── colors.py               # 统一颜色方案
│   └── templates/              # Jinja2模板
│
├── config/                     # 配置层
│   ├── settings.py             # 全局配置类（支持YAML加载）
│   └── stock_lists.py          # 内置股票列表与行业分类
│
├── utils/                      # 工具层
│   ├── logger.py               # Loguru日志系统
│   ├── helpers.py              # 通用辅助函数
│   └── validators.py           # 输入校验
│
├── watchlist/                  # 自选股数据
│   └── default_watchlist.json
│
└── tests/                      # 测试目录
    ├── conftest.py
    ├── test_data/
    ├── test_analysis/
    ├── test_strategy/
    └── test_engine/
```

---

## 🔬 因子清单

### 技术因子（7个）

| 因子名称 | 计算方法 | 逻辑说明 | 方向 |
|----------|----------|----------|------|
| `momentum_20` | 过去20日收益率 | 趋势跟踪——强者恒强 | + |
| `reversal_5` | 过去5日收益率（取负） | 短期超跌反弹 | - |
| `volatility_20` | 过去20日收益率标准差 | 低波动溢价 | - |
| `turnover_20` | 成交量/流通股本 | 流动性衡量 | + |
| `volume_price_corr` | 价格变化与成交量变化的相关性 | 量价配合度 | + |
| `rsi_14` | 相对强弱指标（14日） | 超买超卖均值回归 | - |
| `ma_deviation` | 收盘价/20日均线 - 1 | 均值回归信号 | - |

### 基本面因子（7个）

| 因子名称 | 计算方法 | 逻辑说明 | 方向 |
|----------|----------|----------|------|
| `pe` | 市盈率（取负） | 低PE估值便宜 | - |
| `pb` | 市净率（取负） | 低PB估值便宜 | - |
| `roe` | 净资产收益率 | 高ROE盈利能力强 | + |
| `revenue_growth` | 营收同比增长率 | 业务扩张信号 | + |
| `profit_growth` | 净利润同比增长率 | 利润增长驱动力 | + |
| `debt_ratio` | 资产负债率（取负） | 低负债财务健康 | - |
| `gross_margin` | 毛利率 | 产品竞争力（护城河） | + |

---

## ⚙️ 配置说明

编辑 `config.yaml` 可自定义：

```yaml
# 数据源
data_source:
  primary: akshare
  cache_enabled: true

# 因子权重（以技术因子为例）
technical_factors:
  momentum_20:
    enabled: true
    weight: 0.25

# 综合策略
strategy:
  technical_weight: 0.40    # 技术面总权重
  fundamental_weight: 0.60   # 基本面总权重
  top_n: 20                  # 输出前N只
  normalization: rank         # 标准化方法: rank / zscore / minmax

# 回测参数
backtest:
  start_date: "20250101"
  rebalance_freq: monthly
  commission_rate: 0.0003
  benchmark: "000300"
```

---

## 🧪 演示策略

默认演示策略为**技术40% + 基本面60%**混合：

| 大类 | 权重 | 子因子 | 子权重 |
|------|------|--------|--------|
| 技术面 | 40% | 20日动量 | 1/3 |
| | | 20日波动率（低波动高分） | 1/3 |
| | | 量价配合度 | 1/3 |
| 基本面 | 60% | 市盈率（低PE高分） | 1/3 |
| | | ROE（高ROE高分） | 1/3 |
| | | 营收增长率（高增长高分） | 1/3 |

输出：综合得分最高的**前20只股票**，附带详细分析报告。

---

## 🔧 扩展开发

### 添加自定义技术因子

```python
from factor_technical import TechnicalFactor, TechnicalFactorRegistry

class MyCustomFactor(TechnicalFactor):
    def __init__(self, weight=1.0):
        super().__init__(name="my_factor", weight=weight, direction=1)
    
    def calculate(self, data):
        # 实现因子计算逻辑
        results = {}
        for code, df in data.items():
            results[code] = ...  # 你的计算
        return pd.Series(results)

# 注册因子
TechnicalFactorRegistry.register("my_factor", MyCustomFactor)
```

### 添加自定义基本面因子

```python
from factor_fundamental import FundamentalFactor, FundamentalFactorRegistry

class MyFundamentalFactor(FundamentalFactor):
    def __init__(self, weight=1.0):
        super().__init__(name="my_fund_factor", weight=weight, direction=1)
    
    def calculate(self, data):
        # 实现因子计算逻辑
        ...
```

---

## ⚠️ 免责声明

本工具仅供学习和研究使用，不构成任何投资建议。

- 基于历史数据的回测结果不代表未来表现
- 多因子模型存在过拟合风险
- 投资决策应综合考虑市场环境、风险偏好等因素
- 股市有风险，投资需谨慎

---

## 📄 License

MIT License
