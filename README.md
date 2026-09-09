# 🐂 megoo股票助手

沪深 A 股**职业操盘台** —— 从「选股工具」到「私募级操盘闭环」的 AI 量化助手。

判大势(温度+Quant) → 辨多空(资金) → 挖热点(题材) → 定买卖(三维决策+交易计划)
→ 定风险区(估值+威科夫) → 调仓位(风控) → 验证(回测) → AI日报(PushPlus微信推送)

**技术栈**：Python 3.11 · FastAPI · Jinja2 · akshare / baostock / tushare / 东财直连 · SQLite · Vue3+Vant4+Capacitor(手机App)

---

## ✨ 核心能力

| 模块 | 说明 |
|------|------|
| 🎯 **操盘台** (`/ops`) | 市场温度计(情绪40%+量能20%+估值40%)、题材中心、资金追踪、三维决策、量化分析一站式 |
| 🌡️ 市场温度计 | 0-100 温度 + 安全/中枢/警戒三区 + 仓位建议 |
| 📊 Quant 量化 | 市场画像、风格轮动、风险状态、组合 VaR/夏普/最大回撤/相关性 |
| 💰 资金追踪 | 主力榜(日/3日/5日)、敢死队、龙虎榜、多空对比（多源降级兜底） |
| 🔥 题材中心 | 新题材/热题材挖掘、情绪龙头识别、涨停池首板/连板/炸板 |
| 📐 三维决策 | 长线(周MA)0.4 + 波段(MACD)0.35 + 短线(动量/量比/RSI)0.25 |
| 🏗️ 威科夫吸筹 | 区间识别、Spring 弹簧抄底、SOS 主升启动、量价行为评分 |
| 📋 交易计划 | S/A/B/C 评级、入场区间、目标价(2:1盈亏)、止损、凯利仓位、单笔风险≤2% |
| 🔍 动态选股 | 情绪周期、题材轮动、底部吸筹池、主线龙头池 |
| 🔔 股价预警 | 8 类规则（价格突破/跌破/涨跌幅/成交额/换手/振幅/最高价），交易时段轮询，命中 PushPlus 微信推送，30min 冷却防轰炸 |
| 📰 AI 操盘日报 | DeepSeek 生成操盘日报 + PushPlus 推送微信 |
| ⏪ 回测引擎 | 自选股/策略回测，异步任务磁盘持久化，重启不丢 |
| 📈 排行/筛选 | 技术面+基本面+资金 多因子排行、动态扫描 |
| ⭐ 自选股 | JSON 持久化 + 实时行情 + 预警规则管理 |

## 📱 客户端

- **PC 网页**：FastAPI + Jinja2，浏览器访问 `/dashboard` `/ops` `/ranking` `/watchlist` 等
- **手机 App**：`mobile/` Vue3+Vant4+Capacitor，打包 Android APK
- **微信推送**：PushPlus（日报 + 预警 + 系统告警）

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（复制 .env.example 为 .env）
DEEPSEEK_API_KEY=sk-xxx        # AI 日报用（可选，无则跳过日报）
WECHAT_PUSHPLUS=xxx            # PushPlus token（可选，微信推送用）

# 3. 启动 Web 应用（默认 8010）
python app.py
# 或
cd app && uvicorn main:create_app --factory --port 8010
```

浏览器打开 `http://127.0.0.1:8010/ops` 即可使用操盘台。

> **数据源**：默认免费源（东财/akshare/baostock）零配置可跑；免费源受上游限流与接口变动影响，
> 如需稳定行情可配 Tushare token（见 `config.yaml` / `data/tushare_fetcher.py`）。

## 🔧 常用 API

| 路径 | 说明 |
|------|------|
| `GET /api/ops/overview` | 操盘台总览（温度/题材/资金/三维决策） |
| `GET /api/ops/quant` | Quant 量化分析 |
| `GET /api/ops/plan?codes=600519` | SABC 交易计划 |
| `GET /api/ops/report?codes=...` | AI 操盘日报（Markdown） |
| `POST /api/ops/report/push` | 生成并推送日报到微信 |
| `GET/POST/DELETE /api/alerts/rules` | 股价预警规则 CRUD |
| `POST /api/alerts/check` | 立即手动检查一次预警 |
| `GET /api/ranking` | 股票排行 |
| `POST /api/backtest/run` | 启动回测任务 |

## 🧪 测试

```bash
python -m pytest tests/ -q      # 全部测试（含预警引擎 10 项）
```

## 📄 免责声明

本项目仅供**学习与技术研究**，不构成任何投资建议。股市有风险，投资需谨慎。
数据源来自公开接口，可能延迟、中断或存在错误；历史回测不代表未来收益。

## 📝 License

[MIT](LICENSE)
