"""
职业经理人模块单元测试
======================
覆盖：市场温度计 / 题材中心 / 资金追踪 / 三维决策 / 估值空间 / 日报渲染
全部使用 mock 数据，不依赖真实网络。
"""
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import pytest

from analysis.market_temperature import MarketTemperature
from analysis.theme_center import ThemeCenter
from analysis.money_flow import MoneyFlow
from analysis.decision_signals import DecisionSignals
from analysis.valuation_space import ValuationSpace
from app.services.daily_report_service import DailyReportService


# ═══════════════════════════════════════════════════════════════
# 合成K线数据
# ═══════════════════════════════════════════════════════════════

def make_kline(n=200, seed=42):
    """合成日K线（上升趋势 + 随机波动）"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-08-25", periods=n)
    close = 10 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, n)))
    volume = rng.integers(100000, 500000, n).astype(float)
    return pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def make_activity():
    """乐咕市场活跃度 mock"""
    return {
        "上涨": 3000.0, "下跌": 1500.0, "平盘": 200.0,
        "涨停": 70.0, "跌停": 5.0, "真实涨停": 66.0,
    }


def make_index_valuation():
    """指数估值 mock（10年数据，当前PE分位 ~30%）"""
    dates = pd.bdate_range(end="2026-08-25", periods=2500)
    pe = 8 + np.sin(np.arange(2500) / 300) * 4 + np.arange(2500) / 2500 * 2
    return pd.DataFrame({"trade_date": dates, "pe_ttm": pe})


def make_concept_boards():
    """新浪概念资金流 mock"""
    return pd.DataFrame({
        "行业": ["转基因", "粮食概念", "光伏新技术", "特斯拉FSD", "商业航天"],
        "行业指数": [1787.67, 865.15, 142.40, 1597.94, 900.0],
        "行业-涨跌幅": [3.81, 3.60, 2.50, 2.41, 1.80],
        "流入资金": [24.82, 54.97, 80.0, 120.0, 30.0],
        "流出资金": [28.84, 59.88, 70.0, 110.0, 28.0],
        "净额": [-4.02, -4.91, 10.0, 10.0, 2.0],
        "公司家数": [21, 48, 100, 60, 25],
        "领涨股": ["万向德农", "金健米业", "隆基绿能", "德赛西威", "中国卫星"],
        "领涨股-涨跌幅": [10.03, 10.05, 8.0, 7.5, 9.0],
    })


def make_limit_up_pool():
    """涨停池 mock"""
    return pd.DataFrame({
        "代码": ["300001", "300002", "300003", "300004"],
        "名称": ["楚天龙", "深中华A", "汉森制药", "英维克"],
        "涨跌幅": [10.0, 10.0, 10.0, 9.98],
        "最新价": [10.0, 20.0, 30.0, 40.0],
        "封板资金": [1e8, 2e8, 3e8, 4e8],
        "连板数": [3, 4, 5, 1],
        "所属行业": ["题材A", "题材B", "题材C", "算力"],
        "涨停统计": ["3/3", "4/4", "5/5", "1/1"],
    })


def make_fund_flow_rank():
    """个股资金流排行 mock"""
    return pd.DataFrame({
        "代码": ["600001", "600002", "600003", "600004", "600005"],
        "名称": ["A股", "B股", "C股", "D股", "E股"],
        "今日涨跌幅": [10.0, 6.0, 3.0, -2.0, 9.98],
        "今日主力净流入-净额": [5e8, 3e8, 1e8, -2e8, 4e8],
        "今日主力净流入-净占比": [12.0, 8.0, 4.0, -6.0, 10.0],
    })


def make_lhb():
    """龙虎榜 mock"""
    return pd.DataFrame({
        "代码": ["600001", "600002"], "名称": ["亨通光电", "山东黄金"],
        "上榜日": [pd.Timestamp("2026-08-25"), pd.Timestamp("2026-08-21")],
        "收盘价": [10.0, 20.0], "涨跌幅": [9.0, 5.0],
        "龙虎榜净买额": [5e8, 3e8], "上榜原因": ["日涨幅偏离值达7%", "日换手率达20%"],
    })


# ═══════════════════════════════════════════════════════════════
# 1. 市场温度计
# ═══════════════════════════════════════════════════════════════

class TestMarketTemperature:
    def setup_method(self):
        self.mt = MarketTemperature()

    def test_emotion_score(self):
        score = self.mt._score_emotion(make_activity())
        assert 0 <= score <= 100
        # 3000涨 1500跌 → 66.7%，涨停70家 → +0分区间
        assert score > 55

    def test_valuation_score(self):
        score = self.mt._score_valuation(make_index_valuation())
        assert 0 <= score <= 100

    def test_compute_temperature(self, monkeypatch):
        monkeypatch.setattr("analysis.market_temperature.fetch_market_activity",
                            lambda: make_activity())
        monkeypatch.setattr("analysis.market_temperature.fetch_index_valuation",
                            lambda s="上证50": make_index_valuation())
        result = self.mt.compute_temperature()
        assert "temperature" in result
        assert "zone" in result
        assert result["zone"] in ("安全边界区", "价值中枢区", "风险警戒区", "极端区")
        assert 0 <= result["temperature"] <= 100
        assert "advice" in result

    def test_zone_mapping(self, monkeypatch):
        monkeypatch.setattr("analysis.market_temperature.fetch_market_activity",
                            lambda: make_activity())
        monkeypatch.setattr("analysis.market_temperature.fetch_index_valuation",
                            lambda s="上证50": make_index_valuation())
        mt = MarketTemperature()
        mt._score_emotion = lambda a: 90
        mt._score_volume = lambda a: 90
        mt._score_valuation = lambda v: 90
        result = mt.compute_temperature()
        assert result["temperature"] >= 70
        assert result["zone"] == "风险警戒区" or result["zone"] == "极端区"

    def test_low_temp_safe(self, monkeypatch):
        monkeypatch.setattr("analysis.market_temperature.fetch_market_activity",
                            lambda: make_activity())
        monkeypatch.setattr("analysis.market_temperature.fetch_index_valuation",
                            lambda s="上证50": make_index_valuation())
        mt = MarketTemperature()
        mt._score_emotion = lambda a: 10
        mt._score_volume = lambda a: 10
        mt._score_valuation = lambda v: 10
        result = mt.compute_temperature()
        assert result["temperature"] < 30
        assert result["zone"] == "安全边界区" or result["zone"] == "极端区"


# ═══════════════════════════════════════════════════════════════
# 2. 题材中心
# ═══════════════════════════════════════════════════════════════

class TestThemeCenter:
    def setup_method(self):
        self.tc = ThemeCenter(top_n=5)

    def test_new_themes(self, monkeypatch):
        monkeypatch.setattr("analysis.theme_center.fetch_concept_boards",
                            lambda: make_concept_boards())
        themes = self.tc.get_new_themes()
        assert len(themes) == 5
        assert themes[0]["name"] == "转基因"
        assert "pct_chg" in themes[0]
        assert "leader" in themes[0]

    def test_hot_themes(self, monkeypatch):
        monkeypatch.setattr("analysis.theme_center.fetch_concept_boards",
                            lambda: make_concept_boards())
        monkeypatch.setattr("analysis.theme_center.fetch_limit_up_pool",
                            lambda date="": make_limit_up_pool())
        hot = self.tc.get_hot_themes()
        assert len(hot) > 0
        assert all("heat_score" in x for x in hot)
        # 按热度排序
        scores = [x["heat_score"] for x in hot]
        assert scores == sorted(scores, reverse=True)

    def test_sentiment_stocks(self, monkeypatch):
        monkeypatch.setattr("analysis.theme_center.fetch_limit_up_pool",
                            lambda date="": make_limit_up_pool())
        senti = self.tc.get_sentiment_stocks()
        assert len(senti) == 4
        # 高标龙头（5连板汉森制药）排最前
        assert senti[0]["tag"] == "高标龙头"
        assert senti[0]["consecutive_days"] == 5


# ═══════════════════════════════════════════════════════════════
# 3. 资金追踪
# ═══════════════════════════════════════════════════════════════

class TestMoneyFlow:
    def setup_method(self):
        self.mf = MoneyFlow(top_n=5)

    def test_main_flow(self, monkeypatch):
        monkeypatch.setattr("analysis.money_flow.fetch_fund_flow_rank",
                            lambda i: make_fund_flow_rank())
        rows = self.mf.get_main_flow("今日")
        assert len(rows) == 5
        assert rows[0]["name"] == "A股"  # 主力净流入最大
        assert rows[0]["main_net"] == 5e8

    def test_daredevil(self, monkeypatch):
        monkeypatch.setattr("analysis.money_flow.fetch_fund_flow_rank",
                            lambda i: make_fund_flow_rank())
        rows = self.mf.get_daredevil_flow()
        # 涨幅≥5% 且主力净流入>0：A股(10%)、B股(6%)、E股(9.98%)
        assert len(rows) == 3
        assert all(r["pct_chg"] >= 5 for r in rows)

    def test_daredevil_fallback(self, monkeypatch):
        """东财接口失败 → 涨停池降级"""
        monkeypatch.setattr("analysis.money_flow.fetch_fund_flow_rank",
                            lambda i: None)
        monkeypatch.setattr("analysis.theme_center.fetch_limit_up_pool",
                            lambda date="": make_limit_up_pool())
        rows = self.mf.get_daredevil_flow()
        assert len(rows) == 4
        assert rows[0]["source"] == "涨停池降级"
        assert rows[0]["name"] == "英维克"  # 封板资金最大

    def test_bull_bear(self, monkeypatch):
        monkeypatch.setattr("analysis.money_flow.fetch_fund_flow_rank",
                            lambda i: make_fund_flow_rank())
        bb = self.mf.get_bull_bear()
        assert bb["bull_count"] == 4  # A/B/C/E 净流入
        assert bb["bear_count"] == 1
        assert bb["direction"] == "多方占优"

    def test_lhb(self, monkeypatch):
        monkeypatch.setattr("analysis.money_flow.fetch_lhb_detail",
                            lambda start_date="", end_date="": make_lhb())
        rows = self.mf.get_lhb()
        assert len(rows) == 2
        assert rows[0]["name"] == "亨通光电"


# ═══════════════════════════════════════════════════════════════
# 4. 三维决策
# ═══════════════════════════════════════════════════════════════

class TestDecisionSignals:
    def test_comprehensive(self):
        df = make_kline(200)
        sig = DecisionSignals().comprehensive(df)
        assert "long_term" in sig
        assert "swing" in sig
        assert "short_term" in sig
        assert "composite_score" in sig
        assert 0 <= sig["composite_score"] <= 100
        assert sig["action"] in ("买入/加仓", "卖出/减仓", "持有/观望")
        for dim in ("long_term", "swing", "short_term"):
            assert sig[dim]["signal"] in ("多", "空", "观望")
            assert 0 <= sig[dim]["score"] <= 100

    def test_kline_wrapper_compat(self):
        """兼容 KLineData 包装对象"""
        from data.models import KLineData
        df = make_kline(200)
        wrapper = KLineData(code="000001", df=df)
        sig = DecisionSignals().comprehensive(wrapper)
        assert "composite_score" in sig

    def test_insufficient_data(self):
        df = make_kline(30)
        sig = DecisionSignals().comprehensive(df)
        # 数据不足 → 长线/波段观望，综合中性
        assert sig["long_term"]["signal"] == "观望"
        assert sig["swing"]["signal"] == "观望"
        assert sig["composite_score"] <= 60

    def test_strong_uptrend(self):
        """强上升趋势 → 长线做多"""
        rng = np.random.default_rng(7)
        n = 450  # 约90周，满足长线70周要求
        close = 10 * np.cumprod(1 + rng.normal(0.003, 0.015, n))
        df = pd.DataFrame({
            "date": pd.bdate_range(end="2026-08-25", periods=n),
            "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
            "close": close,
            "volume": rng.integers(200000, 800000, n).astype(float),
        })
        sig = DecisionSignals().comprehensive(df)
        assert sig["long_term"]["signal"] == "多"


# ═══════════════════════════════════════════════════════════════
# 5. 估值空间
# ═══════════════════════════════════════════════════════════════

class TestValuationSpace:
    def make_hist(self):
        dates = pd.bdate_range(end="2026-08-25", periods=1000)
        pe = np.linspace(8, 20, 1000)
        pb = np.linspace(1, 4, 1000)
        return pd.DataFrame({"trade_date": dates, "pe_ttm": pe, "pb": pb})

    def test_analyze_safe(self, monkeypatch):
        """当前 PE 处于历史低位 → 安全边界区"""
        hist = self.make_hist()
        hist.loc[hist.index[-1], "pe_ttm"] = 9.0  # 接近最低
        hist.loc[hist.index[-1], "pb"] = 1.2
        monkeypatch.setattr("analysis.valuation_space.fetch_pe_pb_history",
                            lambda s: hist)
        result = ValuationSpace().analyze("000001")
        assert result["available"] is True
        assert result["zone"] == "安全边界区"

    def test_analyze_warn(self, monkeypatch):
        hist = self.make_hist()
        hist.loc[hist.index[-1], "pe_ttm"] = 19.0  # 接近最高
        hist.loc[hist.index[-1], "pb"] = 3.8
        monkeypatch.setattr("analysis.valuation_space.fetch_pe_pb_history",
                            lambda s: hist)
        result = ValuationSpace().analyze("000001")
        assert result["zone"] == "风险警戒区"

    def test_analyze_center(self, monkeypatch):
        hist = self.make_hist()
        # 末值设为中间水平 → 中枢区
        hist.loc[hist.index[-1], "pe_ttm"] = 14.0
        hist.loc[hist.index[-1], "pb"] = 2.5
        monkeypatch.setattr("analysis.valuation_space.fetch_pe_pb_history",
                            lambda s: hist)
        result = ValuationSpace().analyze("000001")
        assert result["zone"] == "价值中枢区"

    def test_analyze_no_data(self, monkeypatch):
        monkeypatch.setattr("analysis.valuation_space.fetch_pe_pb_history",
                            lambda s: None)
        result = ValuationSpace().analyze("000001")
        assert result["available"] is False


# ═══════════════════════════════════════════════════════════════
# 6. 日报渲染
# ═══════════════════════════════════════════════════════════════

class TestDailyReport:
    def make_data(self):
        # 直接构造温度数据，避免真实网络调用
        return {
            "temperature": {
                "temperature": 70.2, "zone": "风险警戒区",
                "advice": "风险警戒区：高位过热，控制仓位",
                "scores": {"emotion": 77.1, "volume": 50.0, "valuation": 73.5},
                "details": {"activity": {"上涨": 3000, "下跌": 1500, "涨停": 70, "跌停": 5}},
            },
            "themes": {"hot_themes": [{"name": "转基因", "pct_chg": 3.81, "leader": "万向德农",
                                       "leader_pct": 10.03, "heat_score": 1.9}],
                       "sentiment_stocks": [{"name": "汉森制药", "tag": "高标龙头",
                                             "consecutive_days": 5, "seal_amount": 3e8}]},
            "money": {"bull_bear": {"bull_count": 317, "bear_count": 70,
                                    "net_total": 6098.89, "direction": "多方占优",
                                    "source": "概念板块资金汇总"},
                      "lhb": [{"name": "亨通光电", "code": "600522", "net_buy": 5e8,
                               "reason": "日涨幅偏离值达7%"}]},
            "stocks": [{"code": "000001", "name": "平安银行", "price": 11.5,
                        "action": "持有/观望", "composite_score": 57.5,
                        "long_term": "观望", "swing": "观望", "short_term": "多",
                        "valuation_zone": "价值中枢区", "pe_pct": 45.0}],
            "timestamp": "2026-08-25 22:00:00",
        }

    def test_render_markdown(self):
        svc = DailyReportService()
        md = svc.render_markdown(self.make_data())
        assert "市场温度" in md
        assert "题材热点" in md
        assert "多空资金" in md
        assert "龙虎榜" in md
        assert "情绪个股" in md
        assert "职业经理人今日操作清单" in md
        assert "平安银行" in md

    def test_position_advice(self):
        svc = DailyReportService()
        assert "60-80%" in svc._position_advice("安全边界区")
        assert "20-40%" in svc._position_advice("风险警戒区")
        assert "40-60%" in svc._position_advice("价值中枢区")

    def test_push_no_token(self, monkeypatch):
        monkeypatch.setattr("app.services.daily_report_service.PUSHPLUS_TOKEN", "")
        svc = DailyReportService()
        result = svc.push("标题", "内容")
        assert result["ok"] is False
