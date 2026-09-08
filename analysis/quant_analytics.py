"""
量化分析师（Quant）视角 —— 金融市场大数据分析
============================================
从"看个股"升级为"看市场结构"，专业 Quant 分析框架：

  1. 市场统计画像：指数截面统计（收益/波动/相关性）→ 市场结构
  2. 风格轮动：大小盘 / 价值成长 相对强弱 → 风格切换检测
  3. 风险状态：波动率聚集 + 相关性抬升 → 系统性风险识别
  4. 组合风险：VaR / 最大回撤 / 夏普 / 相关性矩阵 → 组合级风控
  5. 因子截面：对股票池计算主流因子暴露 → 驱动归因

数据源：指数K线（baostock/东财，稳定）+ 现有因子引擎
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from utils.logger import logger
from analysis._cache import ttl_cache


# 指数映射（风格分析用）
INDEX_MAP = {
    "000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
    "000300": "沪深300", "000905": "中证500", "000852": "中证1000",
    "000016": "上证50", "000688": "科创50",
}


@ttl_cache(1800)
def _get_index_kline(code: str, days: int = 250):
    """获取指数K线（30分钟缓存；东财空数据时降级 baostock）"""
    from data.data_utils import get_best_fetcher
    start = (pd.Timestamp.now() - pd.Timedelta(days=int(days * 1.6))).strftime("%Y%m%d")
    end = pd.Timestamp.now().strftime("%Y%m%d")

    # 1. 指数K线直取腾讯（东财 push2his 指数被风控；复用 fetcher 实例省探测+name缓存）
    try:
        from data.data_utils import get_best_fetcher_cached
        fetcher = get_best_fetcher_cached()
        kl = fetcher.get_history_kline(code, "daily", start, end, "qfq", is_index=True)
        if kl is not None:
            df = getattr(kl, "df", kl)
            if df is not None and not df.empty:
                df = df.copy()
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
                return df
    except Exception as e:
        logger.warning(f"指数K线失败(主源) {code}: {e}")

    # 2. baostock 兜底（东财/腾讯均不可用时；指数需显式 sh/sz 前缀）
    return _fetch_index_bs(code, start, end)


_BS_LOCK = __import__("threading").Lock()


def _fetch_index_bs(code: str, start: str, end: str):
    """baostock 指数K线（非线程安全 → 全局锁串行；quant 并行拉指数时防并发 login 崩溃）"""
    _INDEX_BS_MAP = {
        "000001": "sh.000001", "000300": "sh.000300", "000016": "sh.000016",
        "000905": "sh.000905", "000852": "sh.000852", "000688": "sh.000688",
        "399001": "sz.399001", "399006": "sz.399006",
    }
    bs_code = _INDEX_BS_MAP.get(code)
    if not bs_code:
        return None
    import baostock as bs
    import socket as _socket
    with _BS_LOCK:
        old = _socket.getdefaulttimeout()
        _socket.setdefaulttimeout(10)
        try:
            lg = bs.login()
            if lg.error_code == "0":
                # baostock 日期格式要求 YYYY-MM-DD
                bs_start = f"{start[:4]}-{start[4:6]}-{start[6:]}"
                bs_end = f"{end[:4]}-{end[4:6]}-{end[6:]}"
                rs = bs.query_history_k_data_plus(
                    bs_code, "date,open,high,low,close,volume",
                    start_date=bs_start, end_date=bs_end, frequency="d", adjustflag="2")
                rows = []
                while rs and rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                bs.logout()
                if rows:
                    df = pd.DataFrame(rows, columns=rs.fields)
                    for col in ("open", "high", "low", "close", "volume"):
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date").dropna(subset=["close"])
                    logger.info(f"指数K线(baostock兜底): {code} {len(df)}行")
                    return df
        finally:
            _socket.setdefaulttimeout(old)
    return None


class QuantAnalytics:
    """Quant 大数据分析引擎"""

    # ═══════════════════════════════════════════════════════════
    # 1. 市场统计画像（指数截面）
    # ═══════════════════════════════════════════════════════════

    def market_snapshot(self) -> Dict:
        """主要指数截面统计：区间收益/波动/相关性 → 市场结构"""
        from concurrent.futures import ThreadPoolExecutor
        closes = {}

        def _fetch(code):
            return code, _get_index_kline(code)

        with ThreadPoolExecutor(max_workers=6) as ex:
            for code, df in ex.map(_fetch, list(INDEX_MAP)):
                if df is not None and len(df) >= 60:
                    closes[INDEX_MAP[code]] = df["close"]

        if not closes:
            return {"available": False, "msg": "指数数据不可用"}

        frame = pd.DataFrame(closes).dropna()
        if len(frame) < 30:
            return {"available": False, "msg": "指数数据不足"}

        # 区间收益
        ret_20 = (frame.iloc[-1] / frame.iloc[-21] - 1) * 100
        ret_60 = (frame.iloc[-1] / frame.iloc[-61] - 1) * 100
        ret_250 = (frame.iloc[-1] / frame.iloc[0] - 1) * 100

        # 波动率（年化）
        daily_ret = frame.pct_change().dropna()
        vol = daily_ret.std() * np.sqrt(252) * 100

        # 相关性（近60日）
        corr = daily_ret.tail(60).corr()

        rows = []
        for name in frame.columns:
            rows.append({
                "index": name,
                "ret_20": round(float(ret_20.get(name, 0)), 2),
                "ret_60": round(float(ret_60.get(name, 0)), 2),
                "ret_250": round(float(ret_250.get(name, 0)), 2),
                "vol": round(float(vol.get(name, 0)), 1),
            })
        rows.sort(key=lambda x: x["ret_20"], reverse=True)

        # 平均相关性（系统性风险代理）
        n = len(corr.columns)
        avg_corr = 0
        if n > 1:
            tri = corr.values[np.triu_indices(n, 1)]
            avg_corr = float(np.nanmean(tri))

        # 市场宽度：近20日上涨指数比例
        breadth = int((ret_20 > 0).sum()) / len(ret_20)

        return {
            "available": True,
            "indices": rows,
            "avg_correlation": round(avg_corr, 3),
            "breadth_20": round(breadth * 100, 0),
            "market_state": self._market_state(rows, avg_corr),
        }

    @staticmethod
    def _market_state(rows: List[Dict], avg_corr: float) -> str:
        """市场状态判定"""
        if not rows:
            return "未知"
        up_count = sum(1 for r in rows if r["ret_20"] > 0)
        strong = up_count >= len(rows) * 0.6
        weak = up_count <= len(rows) * 0.4
        if strong and avg_corr < 0.5:
            return "多头格局·板块分化（优选个股）"
        if strong:
            return "多头格局·普涨"
        if weak and avg_corr > 0.6:
            return "弱势格局·系统性风险偏高（降仓防御）"
        if weak:
            return "弱势格局·结构分化"
        return "震荡格局·精选波段"

    # ═══════════════════════════════════════════════════════════
    # 2. 风格轮动
    # ═══════════════════════════════════════════════════════════

    def style_rotation(self) -> Dict:
        """风格轮动：大盘vs小盘、成长vs价值"""
        # 大盘=沪深300(000300)，小盘=中证1000(000852)
        # 成长=创业板指(399006)，价值≈上证50(000016)（低估值蓝筹代理）
        pairs = {
            "大盘vs小盘": ("沪深300", "中证1000"),
            "成长vs价值": ("创业板指", "上证50"),
        }
        result = {"styles": [], "rotation_signal": ""}
        code_map = {"沪深300": "000300", "中证1000": "000852", "创业板指": "399006", "上证50": "000016"}
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_pair(label, a, b):
            code_a, code_b = code_map[a], code_map[b]
            with ThreadPoolExecutor(max_workers=2) as ex:
                fa = ex.submit(_get_index_kline, code_a, 90)
                fb = ex.submit(_get_index_kline, code_b, 90)
                return label, a, b, fa.result(), fb.result()

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(_fetch_pair, label, a, b) for label, (a, b) in pairs.items()]
            for fu in futures:
                label, a, b, df_a, df_b = fu.result()
                if df_a is None or df_b is None or len(df_a) < 40 or len(df_b) < 40:
                    continue
                ret_a = float(df_a["close"].iloc[-1] / df_a["close"].iloc[-21] - 1) * 100
                ret_b = float(df_b["close"].iloc[-1] / df_b["close"].iloc[-21] - 1) * 100
                result["styles"].append({
                    "pair": label,
                    "a": {"name": a, "ret_20": round(ret_a, 2)},
                    "b": {"name": b, "ret_20": round(ret_b, 2)},
                    "leader": a if ret_a > ret_b else b,
                    "gap": round(ret_a - ret_b, 2),
                })

        if result["styles"]:
            signals = []
            for s in result["styles"]:
                if abs(s["gap"]) > 2:
                    signals.append(f"{s['pair']}：{s['leader']}占优（差{s['gap']:+.1f}%）")
            result["rotation_signal"] = "；".join(signals) or "风格均衡，无明显切换"
        return result

    # ═══════════════════════════════════════════════════════════
    # 3. 风险状态
    # ═══════════════════════════════════════════════════════════

    def risk_regime(self) -> Dict:
        """风险状态：波动率聚集 + 相关性抬升 → 系统性风险"""
        df = _get_index_kline("000300", 250)
        if df is None or len(df) < 60:
            return {"available": False, "msg": "沪深300数据不足"}

        close = df["close"]
        ret = close.pct_change().dropna()

        # 滚动波动率（20日，年化）
        vol_20 = ret.rolling(20).std().iloc[-1] * np.sqrt(252) * 100
        vol_60 = ret.rolling(60).std().iloc[-1] * np.sqrt(252) * 100
        vol_120 = ret.rolling(120).std().iloc[-1] * np.sqrt(252) * 100

        # 波动率聚集：短期 vs 长期
        vol_ratio = vol_20 / vol_120 if vol_120 > 0 else 1.0

        # 最大回撤（近250日）
        max_dd, curr_dd, _ = self._max_drawdown(close)

        # 风险判定
        if vol_ratio > 1.5 or vol_20 > 35:
            regime, note = "高波动·风险期", f"20日波动率{vol_20:.0f}%（长期{vol_120:.0f}%），波动放大，降杠杆防御"
        elif vol_ratio > 1.2 or vol_20 > 25:
            regime, note = "波动上升", f"波动率抬升（{vol_20:.0f}% vs 长期{vol_120:.0f}%），控制仓位"
        elif vol_20 < 15:
            regime, note = "低波动·蓄势", f"波动率{vol_20:.0f}%处于低位，市场平静，注意方向选择"
        else:
            regime, note = "正常", f"波动率{vol_20:.0f}%，市场平稳"

        return {
            "available": True,
            "regime": regime,
            "note": note,
            "vol_20": round(float(vol_20), 1),
            "vol_60": round(float(vol_60), 1),
            "vol_120": round(float(vol_120), 1),
            "vol_ratio": round(float(vol_ratio), 2),
            "max_drawdown_250": round(max_dd, 1),
            "current_drawdown": round(curr_dd, 1),
        }

    @staticmethod
    def _max_drawdown(close: pd.Series):
        peak = close.cummax()
        dd = (close - peak) / peak
        max_dd = float(dd.min() * 100)
        curr_dd = float(dd.iloc[-1] * 100)
        return max_dd, curr_dd, dd

    # ═══════════════════════════════════════════════════════════
    # 4. 组合风险（对持仓/自选收益序列）
    # ═══════════════════════════════════════════════════════════

    def portfolio_risk(self, returns: pd.DataFrame) -> Dict:
        """组合风险：VaR / 最大回撤 / 夏普 / 相关性"""
        if returns is None or returns.empty or len(returns) < 20:
            return {"available": False, "msg": "收益序列不足"}

        daily = returns.pct_change().dropna()
        if daily.empty:
            return {"available": False, "msg": "收益序列不足"}

        # 组合等权
        port_ret = daily.mean(axis=1)

        # VaR（95%/99%，历史模拟法）
        var95 = float(np.percentile(port_ret, 5) * 100)
        var99 = float(np.percentile(port_ret, 1) * 100)

        # 年化
        ann_ret = float(port_ret.mean() * 252 * 100)
        ann_vol = float(port_ret.std() * np.sqrt(252) * 100)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        # 相关性矩阵（近60日）
        corr = daily.tail(60).corr()
        avg_corr = 0
        n = len(corr.columns)
        if n > 1:
            tri = corr.values[np.triu_indices(n, 1)]
            avg_corr = float(np.nanmean(tri))

        max_dd, curr_dd, _ = self._max_drawdown((1 + port_ret).cumprod())

        return {
            "available": True,
            "var_95": round(var95, 2),
            "var_99": round(var99, 2),
            "annual_return": round(ann_ret, 2),
            "annual_vol": round(ann_vol, 2),
            "sharpe": round(sharpe, 2),
            "max_drawdown": round(max_dd, 2),
            "avg_correlation": round(avg_corr, 3),
        }

    # ═══════════════════════════════════════════════════════════
    # 汇总
    # ═══════════════════════════════════════════════════════════

    def run(self) -> Dict:
        return {
            "market": self.market_snapshot(),
            "style": self.style_rotation(),
            "risk": self.risk_regime(),
            "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def get_quant_analytics() -> Dict:
    """便捷函数"""
    return QuantAnalytics().run()
