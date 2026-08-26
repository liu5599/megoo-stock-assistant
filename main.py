#!/usr/bin/env python3
"""
megoo股票助手 —— 沪深A股多因子选股框架 v1.0
============================================

完整的"数据获取 → 因子计算 → 综合打分 → 选股输出"演示流程。

演示策略：技术40% + 基本面60%混合策略
  - 技术面（40%）：动量 + 低波动 + 量价配合（各1/3权重）
  - 基本面（60%）：低PE + 高ROE + 高营收增长（各1/3权重）

使用方法:
    python main.py demo          运行完整演示流程
    python main.py cli           进入交互式命令行模式
    python main.py --help        查看帮助
"""

import sys
import os
import warnings

# 将项目根目录加入Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 抑制 akshare 的 FutureWarning
warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np
import pandas as pd
from typing import Dict, List, Any

from utils.logger import setup_logger, logger

# 共享数据函数（使用增强版 data_utils）
from data.data_utils import (
    load_config,
    fetch_stock_data,
    fetch_financial_data,
    fetch_batch_kline_with_cache,
    fetch_financial_with_cache,
    build_demo_strategy,
    print_results,
    export_results,
)

from factor_combiner import FactorCombiner
from backtest_engine import BacktestEngine, BacktestConfig, BacktestResult


# ═══════════════════════════════════════════════════════════════
# 数据获取（已在 data_utils 中定义）
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 演示策略（已在 data_utils 中定义）
# ═══════════════════════════════════════════════════════════════

def run_demo():
    """
    运行完整演示流程

    流程:
      1. 加载配置
      2. 初始化数据源
      3. 获取股票池（演示使用热门股票 + 沪深300成分股）
      4. 批量获取K线数据
      5. 批量获取财务数据
      6. 构建演示策略（技术40% + 基本面60%）
      7. 多因子计算与综合打分
      8. 输出Top 20选股结果
    """
    print("\n" + "=" * 80)
    print("  🚀 megoo股票助手 v1.0 — 多因子选股框架演示")
    print("=" * 80)

    # ===== Step 1: 加载配置 =====
    logger.info("Step 1/7: 加载配置...")
    config = load_config()
    logger.info("配置加载完成")

    # ===== Step 2: 自动检测可用数据源 =====
    logger.info("Step 2/7: 自动检测可用数据源...")
    from data.data_utils import get_best_fetcher
    fetcher = get_best_fetcher()
    logger.info(f"数据源: {type(fetcher).__name__}")

    # ===== Step 3: 获取股票池 =====
    stock_pool = None

    # 检查数据源类型，baostock 用较小池
    is_bs = "baostock" in type(fetcher).__name__.lower()
    pool_size = 50 if is_bs else 300

    try:
        from data.stock_manager import StockManager
        stock_mgr = StockManager(fetcher)
        logger.info(f"Step 3/7: 获取沪深A股市值前{pool_size}股票...")
        if hasattr(fetcher, "get_top_n_by_market_cap"):
            stock_pool = fetcher.get_top_n_by_market_cap(pool_size)
        if stock_pool and len(stock_pool) >= 10:
            logger.info(f"✅ 市值排名: {len(stock_pool)}只")
    except Exception as e:
        logger.warning(f"按市值排名失败: {e}")

    # 数据源无市值排名接口或失败 → 用动态成分股
    if not stock_pool or len(stock_pool) < 10:
        logger.info("使用指数成分股构建动态股票池...")

        # 优先沪深300，不行再试中证500
        for idx_name, idx_code in [("沪深300", "000300"), ("中证500", "000905")]:
            try:
                codes = fetcher.get_index_components(idx_code)
                if codes and len(codes) >= 20:
                    stock_pool = [{"code": c, "name": c} for c in codes[:pool_size]]
                    logger.info(f"股票池: {len(stock_pool)}只 ({idx_name}成分股，取前{pool_size})")
                    break
            except Exception:
                continue

        # 全部失败 → 写死的大池子
        if not stock_pool or len(stock_pool) < 20:
            logger.info("成分股获取失败，使用内置股票池...")
            from config.stock_lists import POPULAR_STOCKS
            stock_pool = list(POPULAR_STOCKS)

    logger.info(f"最终股票池: {len(stock_pool)}只")

    stock_codes = [s["code"] for s in stock_pool]

    # ===== Step 4: 获取K线数据（带缓存加速） =====
    logger.info("Step 4/7: 批量获取K线数据...")
    # 使用带缓存的批量获取
    kline_data = fetch_batch_kline_with_cache(fetcher, stock_codes, days=120)

    if len(kline_data) < 5:
        logger.error("K线数据不足，无法继续分析。请检查网络连接。")
        print("\n❌ 数据获取失败——可能原因：")
        print("   1. 网络连接问题，无法访问数据源")
        print("   2. 当前非交易时段，数据源限流")
        print("   3. 数据源API变更，请检查 push2.eastmoney.com 是否可用")
        print("   请稍后重试，或检查网络后运行 python main.py demo")
        return

    # Get names for stocks we have data for
    for code in list(kline_data.keys()):
        name = fetcher.get_stock_name(code)
        # Update stock pool names
        for s in stock_pool:
            if s["code"] == code:
                s["name"] = name

    # ===== Step 5: 获取财务数据（带缓存加速） =====
    logger.info("Step 5/7: 批量获取财务数据...")
    valid_codes = list(kline_data.keys())
    financial_data = fetch_financial_with_cache(fetcher, valid_codes)

    # ===== Step 6: 综合评分与风险管理 =====
    logger.info("Step 6/7: 执行综合评分 + 风险管理（含止损止盈）...")
    from engine.stock_selector import StockSelector

    selector = StockSelector({
        "tech_weight": 0.40, "fund_weight": 0.60,
    })

    # 构建名称映射
    name_map = {s["code"]: s["name"] for s in stock_pool}

    # ===== Step 7: 批量评分排名 =====
    logger.info("Step 7/7: 生成综合排名（含风险调整）...")
    results = selector.rank_stock_pool(
        kline_data, financial_data, name_map, top_n=20
    )

    # ===== 输出结果 =====
    if results.empty:
        print("\n❌ 没有符合条件的股票结果。")
        return results

    print("\n" + selector.format_ranking(results))

    # 输出 Top 3 的详细分析
    print("\n" + "=" * 85)
    print("  📋 Top 3 精选股票详细分析")
    print("=" * 85)
    for _, row in results.head(3).iterrows():
        code = row["code"]
        df = kline_data.get(code)
        fin = financial_data.get(code, {})
        if df is not None and not df.empty:
            report = selector.analyze_stock(
                code, name_map.get(code, code), df, fin,
                total_capital=100000
            )
            print("\n" + selector.format_report(report))

    # 导出结果
    export_results(results, "top20_results.csv")

    return results


# ═══════════════════════════════════════════════════════════════
# 程序入口
# ═══════════════════════════════════════════════════════════════

def main():
    """程序主入口"""
    # 检查命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "demo":
            # 运行演示流程
            try:
                run_demo()
            except KeyboardInterrupt:
                print("\n\n👋 用户中断，再见！")
                sys.exit(0)
            except Exception as e:
                logger.exception(f"演示运行出错: {e}")
                print(f"\n❌ 运行出错: {e}")
                print("   请检查网络连接，确保akshare可正常使用")
                sys.exit(1)
        elif sys.argv[1] == "cli":
            # 进入交互式命令行，去掉 'cli' 参数让 Click 正常解析
            sys.argv.pop(1)
            from presentation.cli import cli
            cli()
        else:
            # 兼容原有的CLI命令（如 analyze/screen/market 等）
            from presentation.cli import cli
            cli()
    else:
        # 默认：打印帮助信息
        print("""
╔══════════════════════════════════════════════════════════════════╗
║           🐂 megoo股票助手 v3.0 — 智能选股+风险管理             ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  使用方法:                                                       ║
║    python main.py demo    运行完整选股+风控流程（推荐）          ║
║    python main.py cli     进入交互式命令行模式                   ║
║    python main.py --help  查看所有CLI命令                       ║
║                                                                  ║
║  演示流程:                                                       ║
║    1. 沪深A股市值前500选股池                                    ║
║    2. 多因子综合评分（技术40% + 基本面60%）                     ║
║    3. 风险评估 + 动态止损止盈                                    ║
║    4. 仓位管理建议 + 卖出信号检测                                ║
║    5. Top 20排名 + Top 3深度报告                                ║
║                                                                  ║
║  核心模块:                                                       ║
║    data/                — 数据获取与缓存                        ║
║    analysis/technical.py — 技术面分析（6维评分）                ║
║    factor_*.py          — 技术+基本面因子（14个）               ║
║    engine/risk_manager.py — 风险管理（止损/止盈/仓位）          ║
║    engine/stock_selector.py — 综合选股评级                      ║
║    backtest_engine.py   — 回测引擎                              ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
        """)


if __name__ == "__main__":
    main()
