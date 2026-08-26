#!/usr/bin/env python3
"""ETF技术面排名分析 — 可独立运行或作为模块导入"""
import os
import sys
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# 自动添加项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from data.baostock_fetcher import BaostockFetcher
from factor_combiner import FactorCombiner
from factor_technical import Momentum20Factor, Volatility20Factor, VolumePriceCorrFactor
import pandas as pd

# 主流ETF列表
DEFAULT_ETFS = [
    ("510300", "沪深300ETF"),   ("510050", "上证50ETF"),
    ("510500", "中证500ETF"),   ("159915", "创业板ETF"),
    ("588000", "科创50ETF"),    ("512880", "证券ETF"),
    ("512100", "中证1000ETF"),  ("159995", "芯片ETF"),
    ("512010", "医药ETF"),      ("515790", "光伏ETF"),
    ("512660", "军工ETF"),      ("510880", "红利ETF"),
    ("159869", "游戏ETF"),      ("516160", "新能源ETF"),
]


def run_etf_analysis(etfs=None, days=200, top_n=5):
    """
    运行ETF技术面排名分析

    Args:
        etfs: ETF列表 [(code, name), ...]，默认使用 DEFAULT_ETFS
        days: 回看天数
        top_n: 返回前N只

    Returns:
        (top_df, full_df): Top N和完整排名的DataFrame
    """
    if etfs is None:
        etfs = DEFAULT_ETFS

    f = BaostockFetcher()
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 1.6)).strftime("%Y%m%d")

    print("正在获取ETF数据...")
    kline_data = {}
    valid_etfs = []
    for code, name in etfs:
        try:
            k = f.get_history_kline(code, start_date=start_date, end_date=end_date, adjust="qfq")
            if k and len(k.df) >= 20:
                kline_data[code] = k.df
                valid_etfs.append((code, name))
                print(f"  ✅ {code} {name}: {len(k.df)}条, 最新 {k.latest_close:.3f}")
            else:
                print(f"  ⚠️ {code} {name}: 数据不足")
        except Exception as e:
            print(f"  ❌ {code} {name}: {e}")

    print(f"\n有效ETF: {len(valid_etfs)}只")

    if len(valid_etfs) < 3:
        print("数据太少，无法分析")
        return pd.DataFrame(), pd.DataFrame()

    combiner = FactorCombiner({
        "strategy": {
            "technical_weight": 1.0, "fundamental_weight": 0.0,
            "top_n": top_n, "normalization": "rank",
            "outlier_method": "winsorize", "outlier_percentile": 0.01,
        }
    })
    combiner.set_factors(
        [
            Momentum20Factor(weight=0.4),
            Volatility20Factor(weight=0.3),
            VolumePriceCorrFactor(weight=0.3),
        ],
        []
    )

    fin_data = {c: {} for c in kline_data}
    results = combiner.compute(kline_data, fin_data)

    name_map = {c: n for c, n in valid_etfs}
    results["name"] = results["code"].map(name_map)

    top_n = results.head(top_n)
    return top_n, results


def print_etf_results(top_n, results):
    """格式化打印ETF分析结果"""
    print()
    print("=" * 75)
    print("  📊 ETF 技术面 Top 推荐")
    print("=" * 75)
    print(f"  策略: 动量40% + 低波动30% + 量价配合30%")
    print()
    print(f"  {'排名':<5} {'代码':<8} {'名称':<12} {'总分':<7} {'动量':<6} {'低波动':<6} {'量价':<6}")
    print("  " + "-" * 65)
    for _, row in top_n.iterrows():
        rank = int(row["rank"])
        stars = "★" * max(1, int(row["total_score"] / 20)) + "☆" * (5 - max(1, int(row["total_score"] / 20)))
        m = row.get("factor_momentum_20", 0)
        v = row.get("factor_volatility_20", 0)
        c = row.get("factor_volume_price_corr", 0)
        print(f"  {rank:<5} {row['code']:<8} {row['name']:<12} {row['total_score']:<7.1f} {m:<6.0f} {v:<6.0f} {c:<6.0f} {stars}")
    print("  " + "-" * 65)

    print(f"\n  📋 完整排名:")
    for _, row in results.iterrows():
        rank = int(row["rank"])
        print(f"  {rank:>2}. {row['code']} {row['name']:<10}  {row['total_score']:.1f}分")

    print(f"""
  ⚠️ ETF分析仅基于技术面，不含基本面。
     建议结合市场趋势、行业轮动综合判断。
  📅 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
""")


if __name__ == "__main__":
    top_n, results = run_etf_analysis()
    if not top_n.empty:
        print_etf_results(top_n, results)
