# megoo股票助手 v4.0 —— AI 功能技术文档（股价预警 / AI问股 / 多通道推送）

> 适用版本：v4.0（2026-09） ｜ 代码量 ≈17,000 行 Python
> 前置文档：`技术文档.md`（v3.0 基础引擎）— 本文档只覆盖 v4 新增 AI 功能。

---

## 0. 架构速览（v4 增量）

```
新增模块
├── app/services/notify.py        统一通知通道（PushPlus / 企微 / 飞书）
├── app/services/price_alert.py   股价预警引擎（规则存储 + 判定 + 轮询线程）
├── app/services/ask_agent.py     AI 问股引擎（策略加载 + 数据装配 + LLM 诊断）
├── app/routers/alerts.py         /api/alerts/*（预警规则 CRUD + 手动检查 + 启停）
├── app/routers/ask.py            /api/ask/*（问股 + SSE 流式）
├── strategies/*.yaml             问股策略声明（零代码扩展）
└── tests/test_price_alerts.py / test_ask_agent.py / test_notify.py
    （+10 / +8 / +12 项测试）
```

完整路由清单见 §6。

---

## 1. 股价预警引擎

### 1.1 设计

对标 daily_stock_analysis 的 15 种预警，落地实时行情可判的 **8 类规则**：

| type | 含义 | 单位 |
|---|---|---|
| `price_above` | 现价 ≥ 目标价（突破） | 元 |
| `price_below` | 现价 ≤ 目标价（跌破） | 元 |
| `pct_above` | 涨跌幅 ≥ X% | % |
| `pct_below` | 涨跌幅 ≤ X% | % |
| `amount_above` | 成交额 ≥ X | 亿 |
| `turnover_above` | 换手率 ≥ X | % |
| `amplitude_above` | 振幅 ≥ X | % |
| `high_above` | 盘中最高价 ≥ 目标价 | 元 |

### 1.2 存储与判重

- **规则持久化**：`cache_data/price_alerts.json`（JSON 数组，线程锁保护）
- **唯一键**：`code:type:value` —— 重复添加自动覆盖（含 enabled/value）
- **推送冷却**：同规则命中后 30 分钟不重复推送（`_last_trigger` 内存 dict；`MEGOO_ALERT_COOLDOWN_MIN` 可调）
- **推送通道**：直走 `notify.send_notify`（PushPlus/企微/飞书全部已配置通道）——不再经 alert_center 的运维告警节流，冷却由本引擎全权负责

### 1.3 轮询线程

- 启动：`app/main.py` lifespan 里 `start_alert_thread()`（幂等，重复调用不重复起线程）
- 周期：默认 60s（`MEGOO_ALERT_INTERVAL`）
- **交易时段判断** `_in_trading_time()`：周一至五 9:15–15:05，其余时间不轮询
- 数据流：`StockManager.get_watchlist_with_quotes()`（自选股 + 实时行情）→ `check_once()` 逐规则判定 → 命中推送
- 非交易时段手动 `/api/alerts/check` 仍可强制检查

### 1.4 文件

- `app/services/price_alert.py`：`load_rules / save_rules / add_rule / remove_rule / toggle_rule / eval_rule / check_once / start_alert_thread / stop_alert_thread`
- `app/routers/alerts.py`：见 §6 API 表
- UI：`app/templates/watchlist.html` 自选页（每行「🔔 设预警」+ 规则管理卡片：停用/删除/立即检查一次）

---

## 2. AI 问股引擎

### 2.1 架构（借鉴 daily_stock_analysis）

```
策略声明(strategies/*.yaml)
    → 用户问题路由(resolve_strategy: 显式名 > 别名 > 默认comprehensive)
    → 数据装配(_collect_stock_data: 复用 ops_stock_detail = K线+三维决策+估值+交易计划+威科夫)
    → 数据摘要(_summarize_data: dict → 紧凑文本, 含评级/入场/目标/止损/估值分位)
    → DeepSeek 诊断(instructions 注入 + 真实数据约束)
    → 回答(同步 JSON 或 SSE 逐字流)
```

### 2.2 策略 YAML（零代码扩展）

`strategies/*.yaml` 格式：

```yaml
name: comprehensive            # 唯一名
display_name: 综合诊断
category: 默认
aliases: [综合, 诊断]           # 路由命中词
instructions: |                # 分析框架（自然语言, 注入 prompt）
  你是从业15年的A股私募基金经理。基于提供的个股真实数据...
required_tools: [stock_detail] # 预留（当前单数据源）
output: markdown
```

新增策略 = 新增一个 YAML，无需改代码。加载器 `load_strategies()` 内存缓存（重启热载）。

### 2.3 路由规则 `resolve_strategy(text)`

1. **显式策略名点名**：`text == name`（如输入 `wyckoff`）
2. **别名子串命中**：如「用威科夫看主力建仓」→ wyckoff
3. 兜底 `comprehensive`

### 2.4 LLM 调用

- 模型：`deepseek-v4-flash`（`MEGOO_LLM_MODEL` 可换）
- 直连 `api.deepseek.com/chat/completions`，**非流式 max_tokens=3000 / temp 0.5**（<3000 会空 content，见坑）
- 无 `DEEPSEEK_API_KEY` 或调用失败 → **确定性模板诊断** `_fallback_answer()`（基于真实评级/动作/点位，明确标注"非投资建议"，不编造）
- `.env` 加载已收进 `app/main.py create_app → _load_env_file()`，**任何入口**（uvicorn factory / app.py）都能读到 key

### 2.5 SSE 流式端点

`POST /api/ask/stream?code=600519&question=...&strategy=...`

事件契约（`text/event-stream`）：

| event | data | 说明 |
|---|---|---|
| `meta` | `{code, strategy}` | 会话元信息 |
| `data` | `{summary}` | 真实行情摘要（装配完成） |
| `delta` | `{delta}` | LLM 逐字增量 |
| `answer` | `{answer, deterministic}` | 完整回答（收尾） |
| `done` | `{}` | 流结束 |
| `error` | `{error}` | 异常 |

实现：FastAPI `StreamingResponse` + 同步生成器（Starlette 自动线程池迭代，不阻塞事件循环）+ DeepSeek `stream:true` 逐行透传。

### 2.6 文件

- `app/services/ask_agent.py`：`load_strategies / resolve_strategy / ask / _collect_stock_data / _summarize_data / _fallback_answer`
- `app/routers/ask.py`：见 §6
- UI：PC `ops.html`（代码+策略下拉+SSE 打字机）；mobile `StockDetail.vue`（textarea+策略单选+同步回答，走 `fetchAsk`）

---

## 3. 统一通知通道

### 3.1 通道（环境变量启用，全部已配置通道都发）

| 通道 | 环境变量 | 发送格式 |
|---|---|---|
| PushPlus | `WECHAT_PUSHPLUS` 或 `PUSHPLUS_TOKEN` | markdown，POST pushplus.plus/send |
| 企业微信 | `WECHAT_WEBHOOK_URL` | text（企微 markdown 标题兼容差，用 text + 【标题】首行），4000 字截断 |
| 飞书 | `FEISHU_WEBHOOK_URL` | text，4000 字截断 |

### 3.2 调用方改造

| 原调用 | 改造后 |
|---|---|
| `alert_center.send_alert(title, content, level)` | 内部走 `send_notify(f"[{level}] {title}", content)`（保留 P0/P1 前缀与 30min event_key 节流）|
| `daily_report_service.push(title, content)` | `send_notify(title, content)` |
| `price_alert._push(title, content)` | `send_notify(title, content)`（冷却由 price_alert 自己管，不双节流）|

### 3.3 返回

`send_notify(title, content) → {ok, msg, channels:[成功], failed:[失败]}`。未配置任何通道返回 `ok:False, msg:"未配置任何通知通道..."`。

---

## 4. 决策账本（评级回看）

> v3.1 已埋基础，v4 补 UI 展示。

- **记录**：`/api/ops/plan` 生成交易计划时 `snapshot_store.save_plans_snapshot()` 批量入库（SQLite `snapshots` 表，同日期同代码覆盖）
- **回看**：`factor_performance.get_performance_report(trade_date, horizon)` —— 对每条计划用**同源收盘价**（现价 vs 快照基准价）算 S/A/B/C 各评级胜率/平均收益/盈亏比/最大亏损
- **明示**：非实盘收益记录，仅复盘研究过程
- UI：`ops.html`「📒 决策账本」卡片（5/10/20 日回看切换）

---

## 5. 手机 App（mobile/）

Vue3 + Vant4 + Capacitor。5 Tab：操盘台 / 个股 / 题材 / 资金 / 日报 + 详情钻取。

| 页面 | 新功能 |
|---|---|
| StockDetail.vue | AI 问股卡片：问题输入 + 策略单选（自动/综合/威科夫）+ 同步回答展示 |
| api/index.js | `fetchAsk(code, question, strategy)` POST `/api/ask`（90s 超时，兼容冷加载）|

后端地址：`.env.production` 的 `VITE_API_BASE`（APK 用局域网 IP）；App 内可改。

---

## 6. API 路由全清单

### 6.1 股价预警 `/api/alerts`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/rules` | 规则列表 + 8 类说明 |
| POST | `/rules?code&name&rule_type&value&enabled` | 新增/覆盖规则 |
| DELETE | `/rules?code&rule_type&value` | 删除规则 |
| POST | `/rules/toggle?code&rule_type&value&enabled` | 启停规则 |
| POST | `/check` | 手动跑一次全部规则（返回命中）|
| POST | `/start` `/stop` | 轮询线程启停 |

### 6.2 AI 问股 `/api/ask`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/strategies` | 列出可用策略（name/display_name/aliases）|
| POST | `/ask?code&question&strategy&with_llm` | 同步问股（默认 POST `/api/ask` 空路径）|
| POST | `/stream?code&question&strategy` | SSE 流式问股 |

### 6.3 原有（摘要）

| 前缀 | 端点 |
|---|---|
| `/api/ops` | overview / lhb / stocks / plan / stock/{code}/detail / theme/{name}/detail / quant / portfolio/risk / snapshots / performance / report / report/push |
| `/api/stock` | search / {code} / {code}/kline / {code}/financial / {code}/compass / factor-history / factor-peer |
| `/api/ranking` | run / status/{task_id} / results/{task_id} |
| `/api/backtest` | run / status/{task_id} / result/{task_id} |
| `/api/watchlist` | CRUD + export/import |
| `/api/market` | overview / sectors |
| `/api/screener` | surge / surge/status / surge/results |
| `/api/system` | status / cache/clear |
| `/` | dashboard / ranking / surge / ops / compare / backtest / watchlist / stock/{code} / theme/{name} / lhb |

---

## 7. 配置（.env）

```bash
# LLM（AI 日报 + 问股）
DEEPSEEK_API_KEY=sk-xxx

# 通知（日报/预警/系统告警，至少配一个）
WECHAT_PUSHPLUS=              # PushPlus
WECHAT_WEBHOOK_URL=           # 企业微信机器人（可选）
FEISHU_WEBHOOK_URL=           # 飞书机器人（可选）

# 预警引擎（可选，默认合理）
MEGOO_ALERT_INTERVAL=60       # 轮询秒数
MEGOO_ALERT_COOLDOWN_MIN=30   # 同规则冷却分钟

# 可选数据源
TUSHARE_TOKEN=
```

---

## 8. 测试

```bash
.venv/bin/python -m pytest tests/ -q
# 130 passed（v3 基线 110 + 预警 10 + 问股 8 + 通知 12 等）
```

新增测试文件：`tests/test_price_alerts.py`（规则 CRUD/判定/冷却，mock 不碰网）、`tests/test_ask_agent.py`（策略加载/路由/模板，mock 不碰 LLM）、`tests/test_notify.py`（三通道 mock HTTP）。

## 9. 已知限制与坑

| 项 | 说明 |
|---|---|
| DeepSeek max_tokens <3000 会空 content | 问股用 3000；日报同规则（api-gateway skill 记录）|
| SSE 端点用同步生成器 | Starlette 自动线程池迭代，实测 305 事件流正常 |
| 预警冷却是内存态 | 重启进程后冷却清零（规则本身持久化）；若需跨重启去重可落盘 last_trigger |
| 问股策略内存缓存 | strategies/ 改动需重启生效（低频，够用）|
| 决策账本回看取"现价 vs 基准价" | 严格意义是 T+now 假设，非 T+N；如需严格按快照日+horizon 需扩展 fetch |

---

*本文档由 Hermes Agent 生成，与 v4.0 代码同步。*
