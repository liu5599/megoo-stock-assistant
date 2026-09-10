"""
数据工具函数
===========
从 main.py 抽取的共享数据获取函数，供 CLI 和 Web App 共用。
智能数据源检测：EastMoney不可用则自动切换baostock。
使用批量API优先 + 顺序访问（baostock不支持并发）+ parquet缓存。
"""
import os
import time
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

from utils.logger import logger

# ── 轻量 TTL 缓存（fetcher 实例复用：探测东财 ~3s + name/连接池 跨请求保留） ──
_fetcher_cache = {"t": 0.0, "obj": None}
_FETCHER_TTL = 60.0


def get_best_fetcher_cached() -> Any:
    """60s 内复用同一 fetcher 实例（东财可用性探测 ~3s/次，不可每次请求都探测）"""
    global _fetcher_cache
    now = time.time()
    if _fetcher_cache["obj"] is not None and now - _fetcher_cache["t"] < _FETCHER_TTL:
        return _fetcher_cache["obj"]
    f = get_best_fetcher()
    _fetcher_cache = {"t": now, "obj": f}
    return f

# ── 缓存目录 ──
CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache_data"
)
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(key: str) -> str:
    h = hashlib.md5(key.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{h}.pkl")


def _read_cache(key: str, max_age_hours: int = 4) -> Optional[pd.DataFrame]:
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    age = time.time() - os.path.getmtime(path)
    if age > max_age_hours * 3600:
        return None
    try:
        return pd.read_pickle(path)
    except Exception:
        return None


def _write_cache(key: str, df: pd.DataFrame):
    try:
        df.to_pickle(_cache_path(key))
    except Exception as e:
        logger.debug(f"缓存写入失败: {e}")


def _is_baostock(fetcher) -> bool:
    """检测是否为 baostock 数据源（不支持并发）"""
    cls_name = type(fetcher).__name__
    return "baostock" in cls_name.lower() or "baostock" in str(type(fetcher).__module__).lower()


def load_config(config_path: str = "config.yaml") -> dict:
    import yaml
    config_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        config_path
    )
    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    logger.warning(f"配置文件 {config_path} 未找到，使用默认配置")
    return {}


def get_best_fetcher():
    """
    自动检测可用的数据源

    优先级: EastMoney (实时行情/全市场/批量财务) > 腾讯K线降级
    注：用实时行情接口（push2.eastmoney.com）检测可用性，因为历史K线接口
    （push2his.eastmoney.com）可能被风控断连；EastMoneyFetcher.get_history_kline
    内部会降级到腾讯K线（web.ifzq.gtimg.cn，稳定快速），K线能力不受影响。
    不再回退 baostock——它顺序获取慢，且当前存在数据传输损坏(decompressing error)。
    """
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })

    # 测试实时行情 API（东财历史K线接口可能被风控，改用实时行情判断可用性）
    try:
        r = session.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f2,f12,f14",
            },
            timeout=8,
        )
        if r.status_code == 200 and r.text and ('"diff"' in r.text or '"data"' in r.text):
            logger.info("✅ EastMoney 实时行情 API 可用")
            from data.eastmoney_fetcher import EastMoneyFetcher
            return EastMoneyFetcher()
        logger.warning("EastMoney 实时行情 API 无响应，改用腾讯K线降级源")
    except Exception as e:
        logger.warning(f"EastMoney API 不可用 ({e})，改用腾讯K线降级源")

    # 东财不可用（限频）：仍返回 EastMoneyFetcher，其 K线走腾讯降级（稳定快速）；
    # 实时行情/财务接口返回空由下游兜底（股票池回退硬编码、基本面因子缺失）。
    from data.eastmoney_fetcher import EastMoneyFetcher
    return EastMoneyFetcher()


def fetch_stock_data(
    fetcher,
    stock_codes: List[str],
    days: int = 120,
) -> Dict[str, pd.DataFrame]:
    """
    批量获取股票K线数据
    自动选择批量或顺序模式（根据数据源类型）
    """
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=int(days * 1.6))).strftime("%Y%m%d")
    is_bs = _is_baostock(fetcher)

    logger.info(f"正在获取 {len(stock_codes)} 只股票的K线数据...")

    # ── 1. 非 baostock 且支持批量 → 批量API ──
    if not is_bs and hasattr(fetcher, "batch_get_history_kline"):
        try:
            kline_data = fetcher.batch_get_history_kline(stock_codes, days=days)
            valid = {
                code: df for code, df in kline_data.items()
                if df is not None and not df.empty and len(df) >= 21
            }
            logger.info(f"批量K线: {len(valid)}/{len(stock_codes)} 有效")
            return valid
        except Exception as e:
            logger.warning(f"批量K线获取失败: {e}")

    # ── 2. 顺序获取（baostock 只能用这个） ──
    kline_data: Dict[str, pd.DataFrame] = {}
    success_count = 0
    total = len(stock_codes)

    for i, code in enumerate(stock_codes):
        try:
            kline = fetcher.get_history_kline(
                code, period="daily",
                start_date=start_date, end_date=end_date,
                adjust="qfq",
            )
            if kline is not None and not kline.df.empty and len(kline.df) >= 21:
                kline_data[code] = kline.df
                success_count += 1
            else:
                logger.debug(f"  {code}: 数据不足")
        except Exception as e:
            logger.debug(f"  {code}: 获取失败 ({e})")

        # baostock 需要间隔
        if is_bs and i < total - 1:
            time.sleep(0.3)

        if (i + 1) % 20 == 0 or i + 1 == total:
            logger.info(f"  K线进度: {i+1}/{total} ({success_count}成功)")

    logger.info(f"K线获取完成: {success_count}/{total}")
    return kline_data


def fetch_financial_data(
    fetcher,
    stock_codes: List[str],
) -> Dict[str, Dict[str, Any]]:
    """
    批量获取股票财务数据
    """
    is_bs = _is_baostock(fetcher)
    logger.info(f"正在获取 {len(stock_codes)} 只股票的财务数据...")

    # ── 非 baostock 且支持批量 ──
    if not is_bs and hasattr(fetcher, "batch_get_financial_data"):
        try:
            raw = fetcher.batch_get_financial_data(stock_codes)
            financial_data = {}
            for code, fin in raw.items():
                if fin.pe is not None:
                    financial_data[code] = {
                        "pe": fin.pe,
                        "pb": fin.pb,
                        "roe": fin.roe,
                        "revenue_growth": fin.revenue_growth,
                        "profit_growth": fin.profit_growth,
                        "debt_ratio": fin.debt_ratio,
                        "gross_margin": fin.gross_margin,
                        "total_market_cap": fin.total_market_cap,
                    }
            logger.info(f"批量财务: {len(financial_data)}/{len(stock_codes)} 有效")
            return financial_data
        except Exception as e:
            logger.warning(f"批量财务获取失败: {e}")

    # ── 顺序获取 ──
    financial_data: Dict[str, Dict] = {}
    success_count = 0
    total = len(stock_codes)

    for i, code in enumerate(stock_codes):
        try:
            fin = fetcher.get_financial_data(code)
            if fin is not None and fin.pe is not None:
                financial_data[code] = {
                    "pe": fin.pe,
                    "pb": fin.pb,
                    "roe": fin.roe,
                    "revenue_growth": fin.revenue_growth,
                    "profit_growth": fin.profit_growth,
                    "debt_ratio": fin.debt_ratio,
                    "gross_margin": fin.gross_margin,
                    "total_market_cap": fin.total_market_cap,
                }
                success_count += 1
        except Exception as e:
            logger.debug(f"  {code}: 财务获取失败 ({e})")

        # baostock 需要间隔
        if is_bs and i < total - 1:
            time.sleep(0.3)

        if (i + 1) % 20 == 0 or i + 1 == total:
            logger.info(f"  财务进度: {i+1}/{total} ({success_count}成功)")

    logger.info(f"财务获取完成: {success_count}/{total}")
    return financial_data


def fetch_batch_kline_with_cache(
    fetcher, stock_codes: List[str], days: int = 120
) -> Dict[str, pd.DataFrame]:
    """带缓存的K线批量获取"""
    today = datetime.now().strftime("%Y%m%d")
    sorted_codes = sorted(stock_codes)
    cache_key = f"kline_{hashlib.md5(json.dumps(sorted_codes, ensure_ascii=False).encode()).hexdigest()[:12]}_{days}d_{today}"

    cached_df = _read_cache(cache_key, max_age_hours=6)
    if cached_df is not None and not cached_df.empty:
        # 重建 {code: df}
        result = {}
        for code in stock_codes:
            mask = cached_df["_code"] == code
            sub = cached_df[mask].drop(columns=["_code"])
            if not sub.empty and len(sub) >= 21:
                result[code] = sub
        if len(result) >= max(5, len(stock_codes) * 0.2):
            logger.info(f"K线缓存命中: {len(result)}/{len(stock_codes)}")
            return result

    kline_data = fetch_stock_data(fetcher, stock_codes, days)

    if kline_data:
        try:
            rows = []
            for code, df in kline_data.items():
                d = df.copy()
                d["_code"] = code
                rows.append(d)
            all_df = pd.concat(rows, ignore_index=True)
            _write_cache(cache_key, all_df)
        except Exception as e:
            logger.debug(f"K线缓存写入失败: {e}")

    return kline_data


def fetch_financial_with_cache(
    fetcher, stock_codes: List[str]
) -> Dict[str, Dict[str, Any]]:
    """带缓存的财务数据批量获取"""
    today = datetime.now().strftime("%Y%m%d")
    sorted_codes = sorted(stock_codes)
    cache_key = f"fin_{hashlib.md5(json.dumps(sorted_codes, ensure_ascii=False).encode()).hexdigest()[:12]}_{today}"

    cached_df = _read_cache(cache_key, max_age_hours=12)
    if cached_df is not None and not cached_df.empty:
        result = {}
        for _, row in cached_df.iterrows():
            code = row["_code"]
            result[code] = {
                k: row[k] for k in
                ["pe", "pb", "roe", "revenue_growth", "profit_growth",
                 "debt_ratio", "gross_margin"]
                if k in row and pd.notna(row[k])
            }
        if len(result) >= max(5, len(stock_codes) * 0.2):
            logger.info(f"财务缓存命中: {len(result)}/{len(stock_codes)}")
            return result

    financial_data = fetch_financial_data(fetcher, stock_codes)

    if financial_data:
        try:
            rows = []
            for code, fin in financial_data.items():
                row = {"_code": code}
                row.update(fin)
                rows.append(row)
            _write_cache(cache_key, pd.DataFrame(rows))
        except Exception as e:
            logger.debug(f"财务缓存写入失败: {e}")

    return financial_data


def build_demo_strategy():
    from factor_technical import (
        Momentum20Factor, Volatility20Factor, VolumePriceCorrFactor,
    )
    from factor_fundamental import PEFactor, ROEFactor, RevenueGrowthFactor
    from factor_combiner import FactorCombiner

    demo_config = {
        "strategy": {
            "technical_weight": 0.40,
            "fundamental_weight": 0.60,
            "top_n": 20,
            "normalization": "rank",
            "outlier_method": "winsorize",
            "outlier_percentile": 0.01,
        }
    }

    combiner = FactorCombiner(demo_config)

    tech_factors = [
        Momentum20Factor(weight=0.34),
        Volatility20Factor(weight=0.33),
        VolumePriceCorrFactor(weight=0.33),
    ]

    fund_factors = [
        PEFactor(weight=0.34),
        ROEFactor(weight=0.33),
        RevenueGrowthFactor(weight=0.33),
    ]

    combiner.set_factors(tech_factors, fund_factors)
    return combiner


def print_results(results: pd.DataFrame, combiner) -> None:
    if results.empty:
        print("\n❌ 没有符合条件的股票结果。")
        return

    summary = combiner.get_summary()

    print("\n" + "=" * 80)
    print("  🐂 megoo股票助手 —— 多因子选股结果")
    print("=" * 80)

    print(f"""
  📊 策略配置:
     技术面权重: {summary['tech_weight'] * 100:.0f}%  |  基本面权重: {summary['fund_weight'] * 100:.0f}%
     标准化方法: {summary['normalization']}

  🔧 技术因子 ({len(summary['tech_factors'])}个):
     {' | '.join(summary['tech_factors'])}

  💰 基本面因子 ({len(summary['fund_factors'])}个):
     {' | '.join(summary['fund_factors'])}

  📈 统计摘要:
     有效股票数: {summary['total_stocks']}
     平均得分:   {summary['mean_score']:.1f}
     最高得分:   {summary['max_score']:.1f}
     最低得分:   {summary['min_score']:.1f}
     得分标准差: {summary['std_score']:.1f}
""")

    print("  " + "─" * 76)
    print(f"  {'排名':<5} {'代码':<8} {'总得分':<8} {'技术面':<8} {'基本面':<8}")
    print("  " + "─" * 76)

    top_n = results.head(20)
    for _, row in top_n.iterrows():
        rank = int(row.get("rank", 0))
        code = row.get("code", "")
        total = row.get("total_score", 0)
        tech = row.get("tech_score", 0)
        fund = row.get("fund_score", 0)
        stars = "★" * int(total / 20) + "☆" * (5 - int(total / 20))
        print(f"  {rank:<5} {code:<8} {total:<8.1f} {tech:<8.1f} {fund:<8.1f} {stars}")

    print("  " + "─" * 76)

    print(f"""
  ⚠️  风险提示:
     本报告基于历史数据和多因子模型自动生成，仅供参考。
     不构成任何投资建议。股市有风险，投资需谨慎。
     请结合市场环境、个人风险偏好等因素做出独立判断。

  📅 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""")


def export_results(results: pd.DataFrame, output_path: str = "results.csv") -> None:
    results.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info(f"结果已导出至: {output_path}")
