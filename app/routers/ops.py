"""
职业经理人面板 API —— 市场温度 / 题材 / 资金 / 三维决策 / 估值 / 日报
对标：指南针 + 容维题材宝典 融合
"""
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Query

from utils.logger import logger

router = APIRouter(prefix="/ops", tags=["ops"])


def _build_warnings(temperature: Dict, themes: Dict, money: Dict) -> List[str]:
    """数据新鲜度/完整性告警（v3.1 SWR增强）"""
    import time as _t
    warnings = []
    threshold_min = float(__import__("os").environ.get("MEGOO_DATA_EXPIRE_THRESHOLD_MIN", "10"))
    now = _t.time()

    def _check_age(ts_str: str, label: str):
        if not ts_str:
            warnings.append(f"{label}: 无时间戳")
            return
        try:
            ts = _t.mktime(_t.strptime(str(ts_str)[:19], "%Y-%m-%d %H:%M:%S"))
            age_min = (now - ts) / 60
            if age_min > threshold_min:
                warnings.append(f"{label}: 数据已过期 {age_min:.0f} 分钟（阈值 {threshold_min:.0f}min）")
        except Exception:
            warnings.append(f"{label}: 时间戳格式异常")

    _check_age(temperature.get("timestamp", ""), "温度计")
    _check_age((themes or {}).get("timestamp", ""), "题材")
    _check_age((money or {}).get("timestamp", ""), "资金")

    if not temperature:
        warnings.append("温度计数据为空")
    if not (themes or {}).get("hot_themes") and not (themes or {}).get("new_themes"):
        warnings.append("题材数据为空")
    if not (money or {}).get("bull_bear"):
        warnings.append("多空数据为空")
    return warnings[:5]


@router.get("/overview")
def ops_overview():
    """盘面总览（温度计+题材+资金+情绪，三模块并行获取）

    结果持久化到磁盘：服务重启后用户立即拿到上次数据（SWR 秒回+后台刷新），
    彻底消灭"首次冷加载 30-40s"等待。
    """
    from analysis.market_temperature import MarketTemperature, clean_jsonable
    from analysis.theme_center import ThemeCenter
    from analysis.money_flow import MoneyFlow

    from concurrent.futures import ThreadPoolExecutor

    def _temp():
        try:
            return MarketTemperature().compute_temperature()
        except Exception as e:
            logger.error(f"温度计失败: {e}")
            return {}

    def _themes():
        try:
            return ThemeCenter(top_n=8).get_overview()
        except Exception as e:
            logger.error(f"题材失败: {e}")
            return {}

    def _money():
        try:
            return MoneyFlow(top_n=8).get_overview()
        except Exception as e:
            logger.error(f"资金失败: {e}")
            return {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        temperature_f = pool.submit(_temp)
        themes_f = pool.submit(_themes)
        money_f = pool.submit(_money)
        temperature = temperature_f.result()
        themes = themes_f.result()
        money = money_f.result()

    result: Dict = clean_jsonable({
        "temperature": temperature,
        "themes": themes,
        "money": money,
        "timestamp": temperature.get("timestamp", ""),
        "data_timestamp": temperature.get("timestamp", "") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "东财/乐咕/涨停池多源",
        "warnings": _build_warnings(temperature, themes, money),
    })

    # 盘面定性（真操盘手内核）：温度=估值贵不贵，regime=今天能不能干
    try:
        from analysis.market_regime import compute_regime
        activity = (temperature or {}).get("details", {}).get("activity") or {}
        bull_bear = (money or {}).get("bull_bear") or {}
        regime = compute_regime(activity, bull_bear)
        result["regime"] = regime

        # 作战小结：一句话盘面定性 + 今日主线
        lines = []
        for ml in ((themes or {}).get("main_lines") or [])[:2]:
            st = ml.get("stage") or ""
            lines.append(f"{ml.get('name')}（{st}{('·' + ml.get('zt_leader') or ml.get('leader') or '') if (ml.get('stage')) else ''}）")
        verdict = regime.get("advice", "")
        if lines:
            verdict += f"｜今日主线：{'、'.join(lines)}"
        result["overview_verdict"] = verdict
    except Exception as e:
        logger.warning(f"盘面定性失败: {e}")

    # 持久化到磁盘（供重启后秒回）
    try:
        import json as _json
        from pathlib import Path as _Path
        _persist = _Path(__file__).parent.parent.parent / "cache_data" / "ops_overview.json"
        _persist.parent.mkdir(parents=True, exist_ok=True)
        _persist.write_text(_json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"overview 持久化失败: {e}")

    return result


@router.get("/lhb")
def ops_lhb(limit: int = Query(50, ge=1, le=100), start_date: str = Query("", description="起始日期 YYYYMMDD，空=近7日")):
    """完整龙虎榜（免费东财源，按净买额降序）"""
    from analysis.market_temperature import clean_jsonable
    from analysis.money_flow import MoneyFlow

    mf = MoneyFlow(top_n=limit)
    rows = clean_jsonable(mf.get_lhb(limit))
    return {
        "lhb": rows,
        "count": len(rows),
        "source": "东方财富(akshare)",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/stocks")
def ops_stocks(codes: str = Query("", description="自选股代码，逗号分隔")):
    """自选股三维决策 + 估值空间"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()][:8]
    if not code_list:
        return {"stocks": [], "msg": "请传入自选股代码，如 codes=000001,600519"}

    from analysis.decision_signals import DecisionSignals
    from analysis.valuation_space import ValuationSpace
    from analysis.market_temperature import clean_jsonable
    from data.data_utils import get_best_fetcher

    fetcher = get_best_fetcher()
    results = []
    for code in code_list:
        try:
            kl = fetcher.get_history_kline(code, "daily", "20250101", "20260825", "qfq")
            if kl is None or kl.data_count < 60:
                continue
            sig = DecisionSignals().comprehensive(kl)
            val = ValuationSpace().analyze(code)
            results.append({
                "code": code,
                "name": getattr(kl, "name", "") or code,
                "price": kl.latest_close,
                "action": sig["action"],
                "composite_score": sig["composite_score"],
                "long_term": sig["long_term"],
                "swing": sig["swing"],
                "short_term": sig["short_term"],
                "valuation": val,
            })
        except Exception as e:
            logger.error(f"个股 {code} 失败: {e}")
    return clean_jsonable({"stocks": results})


@router.get("/plan")
def ops_plan(codes: str = Query("", description="股票代码，逗号分隔"), capital: float = Query(1000000, description="总资金")):
    """交易计划（评级/入场/目标/止损/仓位/逻辑）—— 操盘手核心"""
    from analysis.market_temperature import clean_jsonable
    from analysis.trade_planner import TradePlanner, plan_stock

    code_list = [c.strip() for c in codes.split(",") if c.strip()][:8]
    if not code_list:
        return {"plans": [], "msg": "请传入股票代码，如 codes=000001,600519"}

    # 注意：baostock 非线程安全，必须串行处理（每只约10秒）
    results = []
    for code in code_list:
        try:
            results.append(plan_stock(code, capital=capital))
        except Exception as e:
            logger.error(f"交易计划失败 {code}: {e}")
            results.append({"code": code, "error": str(e), "plan": None})

    plans = [r.get("plan") for r in results if r.get("plan")]
    # 按评级排序 S>A>B>C
    rank = {"S": 0, "A": 1, "B": 2, "C": 3}
    plans.sort(key=lambda p: rank.get(p.get("rating", "C"), 9))

    # 信号快照（v3.1）：自动存档交易计划，供绩效统计与复盘
    try:
        from analysis.snapshot_store import save_plans_snapshot
        saved = save_plans_snapshot(plans)
        if saved:
            logger.info(f"交易计划快照已保存: {saved}条")
    except Exception as e:
        logger.warning(f"快照保存失败: {e}")

    # 组合层：市场温度 → 总仓位建议
    portfolio = {}
    try:
        from analysis.market_temperature import MarketTemperature
        temp = MarketTemperature().compute_temperature()
        portfolio = TradePlanner.portfolio_position(temp.get("zone", "价值中枢区"))
        portfolio["market_zone"] = temp.get("zone", "")
        portfolio["market_temp"] = temp.get("temperature")
    except Exception as e:
        logger.error(f"组合仓位失败: {e}")

    return clean_jsonable({"plans": plans, "portfolio": portfolio})


@router.get("/stock/{code}/detail")
def ops_stock_detail(code: str):
    """个股深度详情（第二层钻取）：K线 + 三维信号 + 估值历史 + 交易计划"""
    from analysis.market_temperature import clean_jsonable
    from analysis.decision_signals import DecisionSignals
    from analysis.valuation_space import ValuationSpace, fetch_pe_pb_history
    from analysis.trade_planner import TradePlanner
    from data.data_utils import get_best_fetcher
    import time as _t

    fetcher = get_best_fetcher()
    kl = fetcher.get_history_kline(code, "daily",
                                   _t.strftime("%Y%m%d", _t.localtime(_t.time() - 600 * 86400)),
                                   _t.strftime("%Y%m%d"), "qfq")
    if kl is None or kl.data_count < 60:
        return clean_jsonable({"code": code, "error": "K线数据不足"})

    df = kl.df
    decision = DecisionSignals().comprehensive(kl)
    valuation = ValuationSpace().analyze(code)
    plan = TradePlanner(total_capital=1_000_000).plan(
        code, getattr(kl, "name", "") or code, kl, decision, valuation)

    # K线（近90日，供前端绘图）
    kline = []
    for _, r in df.tail(90).iterrows():
        kline.append({
            "date": str(r["date"])[:10] if "date" in df.columns else "",
            "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
            "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
            "volume": float(r["volume"]),
        })

    # 估值历史（近2年分位曲线）
    val_hist = []
    try:
        hist = fetch_pe_pb_history(code)
        if hist is not None and not hist.empty:
            for _, r in hist.tail(250).iterrows():
                val_hist.append({
                    "date": str(r["trade_date"])[:10],
                    "pe": round(float(r.get("pe_ttm") or 0), 2),
                    "pb": round(float(r.get("pb") or 0), 2),
                })
    except Exception as e:
        logger.warning(f"估值历史失败 {code}: {e}")

    return clean_jsonable({
        "code": code,
        "name": plan.get("name", code),
        "price": plan.get("price"),
        "decision": decision,
        "valuation": valuation,
        "plan": plan,
        "kline": kline,
        "valuation_history": val_hist,
    })


@router.get("/theme/{board_name}/detail")
def ops_theme_detail(board_name: str):
    """题材详情（第二层钻取）：成分股 + 值得买入评级筛选 + 参数"""
    from analysis.market_temperature import clean_jsonable
    from analysis.theme_center import ThemeCenter
    from analysis.trade_planner import TradePlanner
    from analysis.valuation_space import ValuationSpace
    from data.data_utils import get_best_fetcher
    import time as _t

    detail = ThemeCenter().get_theme_detail(board_name)
    stocks = detail.get("stocks") or []
    if not stocks:
        return clean_jsonable(detail)

    # 对成分股 top 8 跑交易计划评级（标注"值得买入"）
    fetcher = get_best_fetcher()
    enriched = []
    buy_list = []
    for s in stocks[:10]:
        code = s.get("code", "")
        if not code:
            continue
        item = dict(s)
        try:
            kl = fetcher.get_history_kline(
                code, "daily",
                _t.strftime("%Y%m%d", _t.localtime(_t.time() - 400 * 86400)),
                _t.strftime("%Y%m%d"), "qfq")
            if kl is None or kl.data_count < 60:
                item["rating"] = "-"
                enriched.append(item)
                continue
            decision = None
            from analysis.decision_signals import DecisionSignals
            decision = DecisionSignals().comprehensive(kl)
            val = ValuationSpace().analyze(code)
            plan = TradePlanner(total_capital=1_000_000).plan(code, s.get("name", code), kl, decision, val)
            item.update({
                "rating": plan["rating"],
                "action": plan["action"],
                "price": plan["price"],
                "entry_low": plan["entry_low"],
                "entry_high": plan["entry_high"],
                "target_price": plan["target_price"],
                "stop_loss": plan["stop_loss"],
                "position_pct": plan["position_pct"],
                "pe_pct": val.get("pe_pct"),
                "zone": val.get("zone"),
                "wyckoff_phase": (plan.get("wyckoff") or {}).get("phase"),
                "score": decision.get("composite_score") if decision else None,
            })
            if plan["rating"] in ("S", "A"):
                buy_list.append(item)
        except Exception as e:
            logger.warning(f"题材成分评级失败 {code}: {e}")
            item["rating"] = "-"
        enriched.append(item)

    return clean_jsonable({
        "name": detail.get("name"),
        "stocks": enriched,
        "buy_recommend": buy_list,
        "leader": detail.get("leader"),
        "source": detail.get("source", "东财"),
    })


@router.get("/quant")
def ops_quant():
    """Quant 量化大数据分析：市场画像/风格轮动/风险状态/组合风险"""
    from analysis.market_temperature import clean_jsonable
    from analysis.quant_analytics import QuantAnalytics

    q = QuantAnalytics()
    result = {
        "market": q.market_snapshot(),
        "style": q.style_rotation(),
        "risk": q.risk_regime(),
        "timestamp": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    }
    return clean_jsonable(result)


@router.get("/portfolio/risk")
def ops_portfolio_risk(codes: str = Query("", description="持仓/自选股代码，逗号分隔")):
    """组合风险：VaR / 夏普 / 最大回撤 / 相关性矩阵（Quant 视角）"""
    from analysis.market_temperature import clean_jsonable
    from analysis.quant_analytics import QuantAnalytics
    from data.data_utils import get_best_fetcher
    import pandas as pd
    import time as _t

    code_list = [c.strip() for c in codes.split(",") if c.strip()][:10]
    if not code_list:
        return clean_jsonable({"available": False, "msg": "请传入持仓代码，如 codes=600519,000001"})

    fetcher = get_best_fetcher()
    prices = {}
    names = {}
    for code in code_list:
        try:
            kl = fetcher.get_history_kline(
                code, "daily",
                _t.strftime("%Y%m%d", _t.localtime(_t.time() - 180 * 86400)),
                _t.strftime("%Y%m%d"), "qfq")
            if kl is not None:
                df = getattr(kl, "df", None)
                if df is None:
                    df = kl
                if df is not None and not df.empty:
                    s = df.set_index(pd.to_datetime(df["date"]))["close"]
                    prices[code] = s
                    names[code] = getattr(kl, "name", "") or code
        except Exception as e:
            logger.warning(f"组合风险 {code} 失败: {e}")

    if len(prices) < 2:
        return clean_jsonable({"available": False, "msg": "至少需要2只股票的有效K线"})

    frame = pd.DataFrame(prices).dropna()
    risk = QuantAnalytics().portfolio_risk(frame)
    risk["codes"] = [{"code": c, "name": names.get(c, c)} for c in frame.columns]
    risk["available"] = risk.get("available", False) and len(frame) >= 20
    return clean_jsonable(risk)


@router.get("/snapshots")
def ops_snapshots(trade_date: str = Query("", description="日期 YYYY-MM-DD"), limit: int = Query(50)):
    """历史信号快照查询（v3.1 复盘）"""
    from analysis.market_temperature import clean_jsonable
    from analysis import snapshot_store

    rows = snapshot_store.query_snapshots(trade_date=trade_date, limit=limit)
    return clean_jsonable({
        "snapshots": rows,
        "stats": snapshot_store.stats(),
    })


@router.get("/performance")
def ops_performance(trade_date: str = Query("", description="快照日期 YYYY-MM-DD"), horizon: int = Query(5)):
    """信号绩效统计（v3.1 回测验证 S/A 胜率）"""
    from analysis.market_temperature import clean_jsonable
    from analysis.factor_performance import get_performance_report

    return clean_jsonable(get_performance_report(trade_date=trade_date, horizon=horizon))


@router.get("/report")
def ops_report(codes: str = Query("", description="自选股代码，逗号分隔")):
    """生成操盘日报 Markdown"""
    from app.services.daily_report_service import DailyReportService
    from analysis.market_temperature import clean_jsonable

    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    svc = DailyReportService(code_list)
    data = svc.collect()
    return {
        "title": f"🐂 megoo操盘日报",
        "content": svc.render_markdown(data),
        "data": clean_jsonable(data),
    }


@router.post("/report/push")
def ops_report_push(codes: str = Query("", description="自选股代码，逗号分隔")):
    """生成操盘日报并推送微信（PushPlus）"""
    from app.services.daily_report_service import DailyReportService

    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    svc = DailyReportService(code_list)
    result = svc.generate(push=True)
    return result
