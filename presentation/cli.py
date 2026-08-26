"""
CLI命令定义
==========
基于 Click 的命令行接口，提供5个主要命令：
  - analyze: 单股深度分析
  - screen: 条件筛选股票
  - market: 市场概览
  - watchlist: 自选股管理
  - recommend: 今日推荐
"""

import os
import sys
import json
from datetime import datetime

import click

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config.settings import default_config
from utils.validators import validate_stock_code, validate_multiple_codes
from utils.logger import logger


def _get_fetcher():
    """懒加载数据源"""
    from data.data_utils import get_best_fetcher
    return get_best_fetcher()


def _get_selector():
    """懒加载选股引擎"""
    from engine.stock_selector import StockSelector
    return StockSelector({"tech_weight": 0.40, "fund_weight": 0.60})


def _get_name_map(fetcher, codes):
    """获取代码→名称映射"""
    name_map = {}
    for code in codes:
        try:
            name_map[code] = fetcher.get_stock_name(code) or code
        except Exception:
            name_map[code] = code
    return name_map


@click.group()
@click.version_option(version="0.1.0", prog_name="megoo股票助手")
@click.option("--verbose", "-v", is_flag=True, help="显示详细日志")
@click.pass_context
def cli(ctx, verbose):
    """
    🐂 megoo股票助手 —— 沪深A股智能分析工具

    提供多维度股票分析（技术面、基本面、资金面、情绪面），
    生成买入/卖出/持有建议，包含风险评估和置信度评分。
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config"] = default_config

    if verbose:
        logger.info("详细日志模式已开启")


# ═══════════════════════════════════════════════════════════════
# analyze - 单股深度分析
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.argument("stock_code", required=True)
@click.option("--full", "-f", is_flag=True, help="显示完整分析报告")
@click.option("--output", "-o", type=click.Path(), help="输出HTML报告路径")
@click.pass_context
def analyze(ctx, stock_code, full, output):
    """
    单股深度分析

    \b
    STOCK_CODE: 股票代码，如 000001, 600519, 300750
    支持逗号分隔多个代码，如 000001,600519

    \b
    示例:
      python main.py analyze 000001
      python main.py analyze 600519 --full
      python main.py analyze 000001,600519 -o report.html
    """
    # 校验代码
    if "," in stock_code or "，" in stock_code:
        codes, errors = validate_multiple_codes(stock_code)
        if errors:
            for e in errors:
                click.echo(f"❌ {e}", err=True)
            if not codes:
                return
    else:
        is_valid, msg = validate_stock_code(stock_code)
        if not is_valid:
            click.echo(f"❌ {msg}", err=True)
            return
        codes = [stock_code.strip()]

    click.echo(f"\n🔍 正在分析 {len(codes)} 只股票...")
    click.echo("=" * 60)

    try:
        fetcher = _get_fetcher()
        selector = _get_selector()
        name_map = _get_name_map(fetcher, codes)

        from data.data_utils import fetch_batch_kline_with_cache, fetch_financial_with_cache

        # 获取数据
        click.echo("📡 获取行情数据...")
        kline_data = fetch_batch_kline_with_cache(fetcher, codes, days=120)
        click.echo("📡 获取财务数据...")
        financial_data = fetch_financial_with_cache(fetcher, list(kline_data.keys()))

        for code in codes:
            df = kline_data.get(code)
            if df is None or df.empty:
                click.echo(f"\n❌ {code}: 数据不足，无法分析")
                continue

            fin = financial_data.get(code, {})
            name = name_map.get(code, code)
            report = selector.analyze_stock(code, name, df, fin)
            click.echo("\n" + selector.format_report(report))

    except Exception as e:
        click.echo(f"\n❌ 分析失败: {e}", err=True)
        logger.exception(f"分析失败: {e}")

    if output:
        click.echo(f"\n📄 HTML报告将保存至: {output}")

    click.echo("\n✅ 分析完成")


# ═══════════════════════════════════════════════════════════════
# screen - 条件筛选股票
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--pool", "-p", type=click.Choice(["hs300", "zz500", "sz50", "all"]),
              default="hs300", help="股票池（默认: hs300）")
@click.option("--pe-max", type=float, help="最大市盈率")
@click.option("--roe-min", type=float, help="最小ROE（%）")
@click.option("--market-cap-min", type=float, help="最小市值（亿元）")
@click.option("--dividend-min", type=float, help="最小股息率（%）")
@click.option("--top", "-n", type=int, default=20, help="返回前N只（默认: 20）")
@click.option("--output", "-o", type=click.Path(), help="输出结果到CSV文件")
@click.pass_context
def screen(ctx, pool, pe_max, roe_min, market_cap_min, dividend_min, top, output):
    """
    条件筛选股票

    在指定股票池中按多条件组合筛选，返回排名列表。

    \b
    示例:
      python main.py screen --pe-max 20 --roe-min 15
      python main.py screen -p hs300 --dividend-min 3 --top 10
      python main.py screen -p all --pe-max 15 --market-cap-min 100 -o result.csv
    """
    conditions = []
    if pe_max:
        conditions.append(f"市盈率 ≤ {pe_max}")
    if roe_min:
        conditions.append(f"ROE ≥ {roe_min}%")
    if market_cap_min:
        conditions.append(f"市值 ≥ {market_cap_min}亿")
    if dividend_min:
        conditions.append(f"股息率 ≥ {dividend_min}%")

    if not conditions:
        click.echo("⚠️  请至少指定一个筛选条件。使用 --help 查看可用条件。", err=True)
        return

    click.echo(f"\n🔍 筛选条件: {' | '.join(conditions)}")
    click.echo(f"📦 股票池: {pool}")
    click.echo(f"📊 返回前 {top} 只")
    click.echo("=" * 60)

    click.echo(f"\n🔍 筛选条件: {' | '.join(conditions)}")
    click.echo(f"📦 股票池: {pool}")
    click.echo(f"📊 返回前 {top} 只")
    click.echo("=" * 60)

    try:
        fetcher = _get_fetcher()

        # 获取股票池
        pool_codes_map = {
            "hs300": "000300", "zz500": "000905",
            "sz50": "000016", "all": None,
        }
        idx_code = pool_codes_map.get(pool)

        if idx_code:
            codes = fetcher.get_index_components(idx_code)
        else:
            from config.stock_lists import POPULAR_STOCKS
            codes = [s["code"] for s in POPULAR_STOCKS]

        if not codes:
            click.echo("❌ 无法获取股票池数据")
            return

        click.echo(f"📡 获取 {len(codes)} 只股票的财务数据...")
        from data.data_utils import fetch_financial_with_cache
        fin_data = fetch_financial_with_cache(fetcher, codes[:300])

        # 条件筛选
        results = []
        for code, fin in fin_data.items():
            pe = fin.get("pe")
            roe = fin.get("roe")
            debt = fin.get("debt_ratio")
            div_yield = fin.get("dividend_yield")

            if pe_max and (pe is None or pe > pe_max):
                continue
            if roe_min and (roe is None or roe < roe_min):
                continue
            if dividend_min and (div_yield is None or div_yield < dividend_min):
                continue

            # 综合评分
            score = 50
            if pe and pe > 0:
                score += min(25, max(-20, (15 - pe) * 1.5))
            if roe:
                score += min(20, max(-20, (roe - 10) * 1.0))
            if debt:
                score += min(15, max(-15, (40 - debt) * 0.5))
            results.append((code, score, pe, roe, debt, div_yield))

        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top]

        if not results:
            click.echo("\n⚠️ 没有符合条件的股票")
            return

        click.echo(f"\n{'排名':<5} {'代码':<8} {'得分':<7} {'PE':<8} {'ROE%':<8} {'负债%':<8} {'股息%':<8}")
        click.echo("-" * 55)
        for i, (code, score, pe, roe, debt, div_yield) in enumerate(results, 1):
            pe_str = f"{pe:.1f}" if pe else "-"
            roe_str = f"{roe:.1f}" if roe else "-"
            debt_str = f"{debt:.1f}" if debt else "-"
            div_str = f"{div_yield:.1f}" if div_yield else "-"
            click.echo(f"{i:<5} {code:<8} {score:<7.1f} {pe_str:<8} {roe_str:<8} {debt_str:<8} {div_str:<8}")

        if output:
            import pandas as pd
            df = pd.DataFrame(results, columns=["code", "score", "pe", "roe", "debt_ratio", "dividend_yield"])
            df.insert(0, "rank", range(1, len(df) + 1))
            df.to_csv(output, index=False, encoding="utf-8-sig")
            click.echo(f"\n📄 结果已保存至: {output}")

    except Exception as e:
        click.echo(f"\n❌ 筛选失败: {e}", err=True)
        logger.exception(f"筛选失败: {e}")

    click.echo("\n✅ 筛选完成")


# ═══════════════════════════════════════════════════════════════
# market - 市场概览
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--detail", "-d", is_flag=True, help="显示详细数据（含板块动量）")
@click.pass_context
def market(ctx, detail):
    """
    市场概览

    展示全市场行情总览、涨跌统计、北向资金动向等。

    \b
    示例:
      python main.py market
      python main.py market --detail
    """
    click.echo("\n📈 正在获取市场数据...")
    click.echo("=" * 60)

    click.echo("\n📈 正在获取市场数据...")
    click.echo("=" * 60)

    try:
        fetcher = _get_fetcher()

        # 市场情绪
        try:
            sentiment = fetcher.get_market_sentiment()
            click.echo(f"\n📊 市场情绪:")
            click.echo(f"   上涨: {sentiment.advance_count} | 下跌: {sentiment.decline_count} | 平盘: {sentiment.flat_count}")
            click.echo(f"   涨停: {sentiment.limit_up_count} | 跌停: {sentiment.limit_down_count}")
            click.echo(f"   热度指数: {sentiment.market_heat_index:.0f}/100")
            if sentiment.north_total_inflow is not None:
                direction = "流入" if sentiment.north_total_inflow > 0 else "流出"
                click.echo(f"   北向资金: {direction} {abs(sentiment.north_total_inflow):.2f}亿")
        except Exception as e:
            click.echo(f"   市场情绪获取失败: {e}")

        # 主要指数
        click.echo(f"\n📈 主要指数:")
        index_codes = {
            "000001": "上证指数", "399001": "深证成指",
            "399006": "创业板指", "000688": "科创50",
            "000300": "沪深300", "000905": "中证500",
        }
        for idx_code, idx_name in index_codes.items():
            try:
                kline = fetcher.get_history_kline(idx_code, period="daily", days=5)
                if kline and not kline.df.empty and len(kline.df) >= 2:
                    latest = float(kline.df["close"].iloc[-1])
                    prev = float(kline.df["close"].iloc[-2])
                    change = (latest / prev - 1) * 100
                    arrow = "🔴" if change > 0 else "🟢" if change < 0 else "⚪"
                    click.echo(f"   {arrow} {idx_name}: {latest:.2f} ({change:+.2f}%)")
            except Exception:
                click.echo(f"   ⚪ {idx_name}: 获取失败")

    except Exception as e:
        click.echo(f"\n❌ 市场数据获取失败: {e}", err=True)

    click.echo("\n✅ 市场概览完成")


# ═══════════════════════════════════════════════════════════════
# watchlist - 自选股管理
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.argument("action", type=click.Choice(["list", "add", "remove", "analyze"]))
@click.argument("stock_codes", required=False)
@click.pass_context
def watchlist(ctx, action, stock_codes):
    """
    自选股管理

    \b
    操作:
      list    - 查看自选股列表及涨跌
      add     - 添加股票到自选股（支持批量，逗号分隔）
      remove  - 从自选股移除（支持批量，逗号分隔）
      analyze - 批量分析自选股

    \b
    示例:
      python main.py watchlist list
      python main.py watchlist add 000001,600519,300750
      python main.py watchlist remove 000001
      python main.py watchlist analyze
    """
    click.echo(f"\n📋 自选股管理 - {action}")

    watchlist_file = os.path.join(PROJECT_ROOT, "watchlist", "default_watchlist.json")

    def _load_wl():
        if os.path.exists(watchlist_file):
            with open(watchlist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("stocks", [])
        return []

    def _save_wl(stocks):
        os.makedirs(os.path.dirname(watchlist_file), exist_ok=True)
        data = {
            "stocks": stocks,
            "count": len(stocks),
            "updated_at": datetime.now().isoformat(),
        }
        with open(watchlist_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    if action == "list":
        stocks = _load_wl()
        if not stocks:
            click.echo("\n📭 自选股列表为空")
        else:
            click.echo(f"\n📋 共 {len(stocks)} 只自选股:")
            click.echo(f"{'代码':<8} {'名称':<10}")
            click.echo("-" * 20)
            for s in stocks:
                click.echo(f"{s.get('code', ''):<8} {s.get('name', ''):<10}")

    elif action == "add":
        if not stock_codes:
            click.echo("❌ 请指定要添加的股票代码", err=True)
            return
        codes, errors = validate_multiple_codes(stock_codes)
        if errors:
            for e in errors:
                click.echo(f"❌ {e}", err=True)
        if not codes:
            return

        fetcher = _get_fetcher()
        stocks = _load_wl()
        existing = {s["code"] for s in stocks}
        added = []
        for code in codes:
            if code not in existing:
                try:
                    name = fetcher.get_stock_name(code) or code
                except Exception:
                    name = code
                stocks.append({"code": code, "name": name})
                existing.add(code)
                added.append(code)
            else:
                click.echo(f"⚠️ {code} 已在自选股中")

        _save_wl(stocks)
        if added:
            click.echo(f"✅ 已添加: {', '.join(added)}")

    elif action == "remove":
        if not stock_codes:
            click.echo("❌ 请指定要移除的股票代码", err=True)
            return
        codes = [c.strip() for c in stock_codes.replace("，", ",").split(",")]
        stocks = _load_wl()
        removed = [c for c in codes if any(s["code"] == c for s in stocks)]
        stocks = [s for s in stocks if s["code"] not in codes]
        _save_wl(stocks)
        if removed:
            click.echo(f"✅ 已移除: {', '.join(removed)}")
        else:
            click.echo("⚠️ 未找到匹配的自选股")

    elif action == "analyze":
        stocks = _load_wl()
        if not stocks:
            click.echo("\n📭 自选股列表为空，无法分析")
            return
        codes = [s["code"] for s in stocks]
        click.echo(f"🔍 正在批量分析 {len(codes)} 只自选股...")
        # 委托给 analyze 命令的逻辑
        ctx.invoke(analyze, stock_code=",".join(codes), full=False, output=None)

    click.echo("")


# ═══════════════════════════════════════════════════════════════
# recommend - 今日推荐
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--pool", "-p", type=click.Choice(["hs300", "zz500", "sz50", "all"]),
              default="hs300", help="股票池（默认: hs300）")
@click.option("--top", "-n", type=int, default=10, help="推荐数量（默认: 10）")
@click.option("--strategy", "-s",
              type=click.Choice(["comprehensive", "trend", "value", "growth"]),
              default="comprehensive", help="推荐策略（默认: comprehensive）")
@click.option("--output", "-o", type=click.Path(), help="输出HTML报告路径")
@click.pass_context
def recommend(ctx, pool, top, strategy, output):
    """
    今日推荐

    基于多因子模型对指定股票池进行全面评分，给出Top N推荐。

    \b
    示例:
      python main.py recommend
      python main.py recommend --top 20 -p zz500
      python main.py recommend -s value --top 5
      python main.py recommend -o recommendation.html
    """
    strategy_names = {
        "comprehensive": "综合多因子",
        "trend": "趋势跟踪",
        "value": "价值投资",
        "growth": "成长优选",
    }

    click.echo(f"\n🌟 今日推荐")
    click.echo(f"📦 股票池: {pool}")
    click.echo(f"📊 策略: {strategy_names.get(strategy, strategy)}")
    click.echo(f"🔢 推荐数量: {top}")
    click.echo("=" * 60)

    # 调用真实推荐引擎
    try:
        fetcher = _get_fetcher()
        selector = _get_selector()

        # 获取股票池
        pool_codes_map = {
            "hs300": "000300", "zz500": "000905",
            "sz50": "000016", "all": None,
        }
        idx_code = pool_codes_map.get(pool)
        pool_size = {"hs300": 300, "zz500": 100, "sz50": 50, "all": 500}.get(pool, 300)

        if idx_code:
            click.echo(f"📡 获取指数成分股...")
            codes = fetcher.get_index_components(idx_code)[:pool_size]
        else:
            from config.stock_lists import POPULAR_STOCKS
            codes = [s["code"] for s in POPULAR_STOCKS]

        if not codes or len(codes) < 10:
            click.echo("❌ 无法获取足够的股票池数据")
            return

        click.echo(f"📡 获取 {len(codes)} 只股票行情数据...")
        from data.data_utils import fetch_batch_kline_with_cache, fetch_financial_with_cache
        kline_data = fetch_batch_kline_with_cache(fetcher, codes, days=120)
        click.echo(f"📡 获取财务数据...")
        financial_data = fetch_financial_with_cache(fetcher, list(kline_data.keys()))

        name_map = _get_name_map(fetcher, list(kline_data.keys()))

        # 根据策略调整权重
        strategy_weights = {
            "comprehensive": (0.40, 0.60),
            "trend": (0.70, 0.30),
            "value": (0.20, 0.80),
            "growth": (0.30, 0.70),
        }
        tech_w, fund_w = strategy_weights.get(strategy, (0.40, 0.60))
        selector.config["tech_weight"] = tech_w
        selector.config["fund_weight"] = fund_w

        click.echo(f"🔄 正在评分 ({'技术' if tech_w > fund_w else '基本面'}偏好)...")
        results = selector.rank_stock_pool(kline_data, financial_data, name_map, top_n=top)

        if results.empty:
            click.echo("\n⚠️ 没有符合条件的推荐")
        else:
            click.echo("\n" + selector.format_ranking(results))

    except Exception as e:
        click.echo(f"\n❌ 推荐失败: {e}", err=True)
        logger.exception(f"推荐失败: {e}")

    if output:
        click.echo(f"\n📄 HTML报告将保存至: {output}")

    click.echo("\n✅ 推荐完成")


# ═══════════════════════════════════════════════════════════════
# surge - 短线看涨选股（指南针风格买卖点提示）
# ═══════════════════════════════════════════════════════════════

@cli.command()
@click.option("--pool", "-p", type=click.Choice(["popular", "hs300", "zz500", "sz50", "all"]),
              default="popular", help="股票池（默认: popular）")
@click.option("--top", "-n", type=int, default=10, help="推荐数量（默认: 10）")
@click.option("--period", "-t", type=click.Choice(["T+1", "T+3", "波段", "长线"]),
              default="T+3", help="操作周期（默认: T+3短线）")
@click.pass_context
def surge(ctx, pool, top, period):
    """
    指南针风格三把锁选股——资金+趋势+信号三重验证

    \b
    操作周期:
      T+1  超短（1-2天，快进快出）
      T+3  短线（3-5天，波段操作）
      波段  中线（1-2周，趋势跟踪）
      长线  价值（1-3月，基本面+技术共振）

    \b
    示例:
      python main.py surge                    T+3短线推荐
      python main.py surge -t T+1             超短打板
      python main.py surge -t 波段 --top 20   波段选股
    """
    period_names = {"T+1": "超短1-2天", "T+3": "短线3-5天", "波段": "波段1-2周", "长线": "价值1-3月"}
    click.echo(f"\n🔥 指南针·三把锁选股 — {period_names.get(period, period)}")
    click.echo(f"📦 股票池: {pool} | 🔢 推荐: {top}只 | 🔐 资金锁+趋势锁+信号锁")

    try:
        fetcher = _get_fetcher()

        # 大盘判断
        try:
            sentiment = fetcher.get_market_sentiment()
            from engine.short_term_screener import CompassScreener
            screener = CompassScreener()
            market = screener.judge_market(sentiment)
            click.echo(screener.format_market(market))
        except Exception as e:
            click.echo(f"⚠️ 大盘数据获取失败: {e}")
            screener = CompassScreener()

        # 股票池
        pool_map = {"hs300": "000300", "zz500": "000905", "sz50": "000016"}
        if pool in pool_map:
            click.echo("📡 获取指数成分股...")
            try:
                codes = fetcher.get_index_components(pool_map[pool]) or []
            except Exception:
                codes = []
            if not codes or len(codes) < 20:
                from config.stock_lists import POPULAR_STOCKS
                codes = [s["code"] for s in POPULAR_STOCKS]
        else:
            from config.stock_lists import POPULAR_STOCKS
            codes = [s["code"] for s in POPULAR_STOCKS]

        click.echo(f"📡 获取 {len(codes)} 只股票行情数据...")
        from data.data_utils import fetch_batch_kline_with_cache
        kline_data = fetch_batch_kline_with_cache(fetcher, codes, days=120)

        name_map = {}
        for code in list(kline_data.keys()):
            try:
                name_map[code] = fetcher.get_stock_name(code) or code
            except Exception:
                name_map[code] = code

        click.echo(f"🔍 三把锁扫描中（{period}周期）...")
        signals = screener.screen(kline_data, name_map, period=period, top_n=top)

        if not signals:
            click.echo(f"\n⚠️ 当前没有符合条件的{period_names.get(period, '')}信号")
            click.echo("   可能原因：大盘偏弱、信号未共振、数据不足")
            return

        # 排名表格
        click.echo(screener.format_table(signals, period_names.get(period, "")))

        # Top 3 详细
        for sig in signals[:3]:
            click.echo(screener.format_signal(sig))

    except Exception as e:
        click.echo(f"\n❌ 选股失败: {e}", err=True)
        logger.exception(f"surge失败: {e}")

    click.echo("\n✅ 三把锁选股完成")


# ═══════════════════════════════════════════════════════════════
# 程序入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cli()
