"""
AI 操盘日报服务 —— 「职业经理人」每日盘面研判
============================================
汇总：市场温度计 + 题材中心 + 资金追踪 + 三维决策 + 估值空间
输出：结构化 Markdown 日报（职业经理人口吻）
推送：PushPlus 微信推送（WECHAT_PUSHPLUS 环境变量）

LLM 润色（可选）：配置 DEEPSEEK_API_KEY 后自动调用 v4-flash 生成操盘策略解读。
"""
import os
import time
import hashlib
from typing import Dict, List, Optional

import requests

from utils.logger import logger

PUSHPLUS_TOKEN = os.environ.get("WECHAT_PUSHPLUS", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# LLM 润色结果缓存：{md5(markdown): (时间戳, 润色后完整内容)}，TTL 1 小时。
# 相同盘面数据（温度/题材/资金有 5min~1h 缓存）生成的日报内容一致，直接复用润色结果，
# 避免重复调用 DeepSeek API（省 token / 省时 / 防限流）。
_LLM_CACHE: Dict[str, tuple] = {}
_LLM_CACHE_TTL = 3600  # 秒


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        logger.error(f"日报数据收集失败: {e}")
        return default


# ═══════════════════════════════════════════════════════════════
# 数据收集
# ═══════════════════════════════════════════════════════════════

class DailyReportService:
    """职业经理人操盘日报"""

    def __init__(self, watchlist: Optional[List[str]] = None):
        """
        Args:
            watchlist: 自选股代码列表（['000001','600519']），用于个股三维决策
        """
        self.watchlist = watchlist or []

    def collect(self) -> Dict:
        """收集全部盘面数据（各模块独立容错）"""
        from analysis.market_temperature import MarketTemperature
        from analysis.theme_center import ThemeCenter
        from analysis.money_flow import MoneyFlow

        data = {
            "temperature": _safe(lambda: MarketTemperature().compute_temperature(), {}),
            "themes": _safe(lambda: ThemeCenter(top_n=8).get_overview(), {}),
            "money": _safe(lambda: MoneyFlow(top_n=8).get_overview(), {}),
            "quant": _safe(lambda: self._collect_quant(), {}),
            "stocks": self._collect_stock_signals(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return data

    def _collect_quant(self) -> Dict:
        """Quant 量化视角（市场状态/风格轮动/风险状态）"""
        from analysis.quant_analytics import QuantAnalytics

        q = QuantAnalytics()
        return {
            "market": q.market_snapshot(),
            "style": q.style_rotation(),
            "risk": q.risk_regime(),
        }

    def _collect_stock_signals(self) -> List[Dict]:
        """自选股三维决策 + 估值空间"""
        if not self.watchlist:
            return []
        from analysis.decision_signals import DecisionSignals
        from analysis.valuation_space import ValuationSpace
        from data.data_utils import get_best_fetcher

        try:
            fetcher = get_best_fetcher()
        except Exception as e:
            logger.error(f"获取数据源失败: {e}")
            return []

        results = []
        for code in self.watchlist[:8]:  # 最多8只，避免过慢
            try:
                kl = fetcher.get_history_kline(code, "daily",
                                               time.strftime("%Y%m%d", time.localtime(time.time() - 600 * 86400)),
                                               time.strftime("%Y%m%d"), "qfq")
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
                    "long_term": sig["long_term"]["signal"],
                    "swing": sig["swing"]["signal"],
                    "short_term": sig["short_term"]["signal"],
                    "valuation_zone": val.get("zone", ""),
                    "pe_pct": val.get("pe_pct"),
                })
            except Exception as e:
                logger.error(f"个股 {code} 决策失败: {e}")
        return results

    # ---------------- 模板生成 ----------------

    def render_markdown(self, data: Dict) -> str:
        """渲染 Markdown 日报（模板版，不依赖 LLM）"""
        t = data["temperature"]
        money = data["money"]
        themes = data["themes"]
        lines = []

        # 1. 头
        lines.append(f"# 🐂 megoo 职业经理人操盘日报")
        lines.append(f"\n> 生成时间：{data['timestamp']} ｜ 仅供研究参考，不构成投资建议")

        # 2. 市场温度
        zone = t.get("zone", "未知")
        temp = t.get("temperature", "-")
        lines.append(f"\n## 🌡️ 市场温度：{temp}／100 —— {zone}")
        lines.append(f"\n> {t.get('advice', '')}")

        # 2.5 Quant 量化视角
        q = data.get("quant", {})
        q_market = q.get("market") or {}
        q_style = q.get("style") or {}
        q_risk = q.get("risk") or {}
        if q_market.get("available") or q_style.get("styles"):
            lines.append(f"\n## 🧮 Quant 量化视角")
            if q_market.get("available"):
                lines.append(f"\n- **市场状态**：{q_market.get('market_state', '未知')}（宽度{q_market.get('breadth_20', '-')}%，平均相关性{q_market.get('avg_correlation', '-')}）")
            for st in (q_style.get("styles") or [])[:2]:
                lines.append(f"- **风格轮动**：{st['pair']} → {st['leader']}占优（{st['a']['name']} {st['a']['ret_20']:+.1f}% vs {st['b']['name']} {st['b']['ret_20']:+.1f}%）")
            if q_risk.get("available"):
                lines.append(f"- **风险状态**：{q_risk.get('regime', '未知')}（20日波动{q_risk.get('vol_20', '-')}%，250日最大回撤{q_risk.get('max_drawdown_250', '-')}%）")
        if "details" in t and t["details"].get("activity"):
            act = t["details"]["activity"]
            up = act.get("上涨", 0)
            down = act.get("下跌", 0)
            lu = act.get("涨停", 0)
            ld = act.get("跌停", 0)
            lines.append(f"\n- 上涨 {up} 家 ｜ 下跌 {down} 家 ｜ 涨停 {lu} 家 ｜ 跌停 {ld} 家")
        scores = t.get("scores", {})
        lines.append(f"- 情绪分 {scores.get('emotion', '-')} ｜ 量能分 {scores.get('volume', '-')} ｜ 估值分位 {scores.get('valuation', '-')}%")

        # 3. 多空资金
        bb = money.get("bull_bear", {})
        lines.append(f"\n## ⚔️ 多空资金：{bb.get('direction', '数据不足')}")
        lines.append(f"\n- 多方 {bb.get('bull_count', 0)} 个板块 ｜ 空方 {bb.get('bear_count', 0)} 个板块 ｜ 净流入 {bb.get('net_total', 0)} 亿（{bb.get('source', '')}）")

        # 4. 题材热点
        lines.append(f"\n## 🔥 今日题材热点")
        hot = themes.get("hot_themes", [])
        if hot:
            for i, x in enumerate(hot[:5], 1):
                leader = x.get("leader", "—")
                lp = x.get("leader_pct", "")
                lines.append(f"{i}. **{x.get('name', '')}** {x.get('pct_chg', 0):+.2f}% ｜ 领涨：{leader} {lp}% ｜ 热度 {x.get('heat_score', 0)}")
        else:
            lines.append("\n- 题材数据暂不可用")

        # 5. 情绪个股
        lines.append(f"\n## ⚡ 情绪个股（高标）")
        senti = themes.get("sentiment_stocks", [])
        if senti:
            for i, x in enumerate(senti[:5], 1):
                lines.append(f"{i}. **{x.get('name', '')}** ｜ {x.get('tag', '')} ｜ 连板 {x.get('consecutive_days', '?')} ｜ 封板 {round((x.get('seal_amount') or 0) / 1e8, 2)} 亿")
        else:
            lines.append("\n- 今日无涨停数据")

        # 6. 主力/龙虎榜
        lines.append(f"\n## 💰 大资金动向（龙虎榜）")
        lhb = money.get("lhb", [])
        if lhb:
            for i, x in enumerate(lhb[:5], 1):
                lines.append(f"{i}. **{x.get('name', '')}**（{x.get('code', '')}）净买 {round((x.get('net_buy') or 0) / 1e8, 2)} 亿 ｜ 原因：{x.get('reason', '')[:30]}")
        else:
            lines.append("\n- 龙虎榜数据暂不可用")

        # 7. 自选股决策
        if data.get("stocks"):
            lines.append(f"\n## 📋 自选股三维决策")
            for s in data["stocks"]:
                lines.append(f"- **{s['name']}**（{s['code']}）现价 {s['price']} ｜ 综合 {s['composite_score']} → **{s['action']}** ｜ 长线{s['long_term']} 波段{s['swing']} 短线{s['short_term']} ｜ 估值：{s['valuation_zone']}")

        # 8. 职业经理人操作清单
        lines.append(f"\n## 🎯 职业经理人今日操作清单")
        lines.append(f"\n1. 仓位：{self._position_advice(zone)}")
        lines.append(f"2. 方向：{self._direction_advice(money)}")
        lines.append(f"3. 纪律：单笔止损≤7%，总仓位回撤≥15%强制降仓，不追高不恐慌")

        lines.append(f"\n---")
        lines.append(f"\n*本报告由 megoo股票助手自动生成，数据来自公开行情接口，仅供参考。*")
        return "\n".join(lines)

    @staticmethod
    def _position_advice(zone: str) -> str:
        mapping = {
            "安全边界区": "可加仓至 60-80%（分批布局低估标的）",
            "价值中枢区": "维持 40-60% 中性仓位（精选个股）",
            "风险警戒区": "降至 20-40%（只做强势股快进快出）",
            "极端区": "降至 20% 以下或空仓等待",
        }
        return mapping.get(zone, "维持 40-60% 中性仓位")

    @staticmethod
    def _direction_advice(money: Dict) -> str:
        bb = money.get("bull_bear", {})
        direction = bb.get("direction", "")
        if "多方" in direction:
            return "跟随主力资金方向，优先题材龙头与主力净流入标的"
        if "空方" in direction:
            return "防御为主，降低仓位，等待资金回流信号"
        return "多空均衡，轻仓试错，等待方向选择"

    # ---------------- LLM 润色（可选） ----------------

    def enhance_with_llm(self, markdown: str) -> str:
        """调用 DeepSeek v4-flash 生成职业经理人策略解读（无 key 时原样返回）

        带本地缓存：相同 markdown 1 小时内直接复用润色结果，避免重复调用 LLM。
        """
        if not DEEPSEEK_API_KEY:
            return markdown

        cache_key = hashlib.md5(markdown.encode("utf-8")).hexdigest()
        hit = _LLM_CACHE.get(cache_key)
        if hit and time.time() - hit[0] < _LLM_CACHE_TTL:
            logger.info("🧠 LLM 润色命中缓存，直接复用")
            return hit[1]

        try:
            prompt = (
                "你是资深私募基金经理。基于以下A股盘面数据日报，写一段300字以内的策略解读，"
                "要求：结论先行、给出仓位和方向建议、点出风险、语气专业冷静。不要重复数据表格。\n\n"
                + markdown
            )
            resp = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 3000,
                    "temperature": 0.7,
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if content:
                result = markdown + f"\n\n## 🧠 基金经理解读\n\n{content}"
                _LLM_CACHE[cache_key] = (time.time(), result)
                logger.info(f"🧠 LLM 润色完成并已缓存（缓存 {len(_LLM_CACHE)} 条）")
                return result
        except Exception as e:
            logger.error(f"LLM 润色失败，使用模板版: {e}")
        return markdown

    # ---------------- 推送 ----------------

    def push(self, title: str, content: str) -> Dict:
        """PushPlus 微信推送"""
        if not PUSHPLUS_TOKEN:
            return {"ok": False, "msg": "未配置 WECHAT_PUSHPLUS"}
        try:
            resp = requests.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": PUSHPLUS_TOKEN,
                    "title": title,
                    "content": content,
                    "template": "markdown",
                },
                timeout=30,
            )
            data = resp.json()
            return {"ok": data.get("code") == 200, "msg": data.get("msg", "")}
        except Exception as e:
            logger.error(f"PushPlus 推送失败: {e}")
            return {"ok": False, "msg": str(e)}

    # ---------------- 一键生成 ----------------

    def generate(self, push: bool = False, title: str = "") -> Dict:
        """生成日报（可选推送）"""
        from analysis.market_temperature import clean_jsonable
        data = self.collect()
        markdown = self.render_markdown(data)
        markdown = self.enhance_with_llm(markdown)
        title = title or f"🐂 megoo操盘日报 {time.strftime('%m-%d')}"
        result = {
            "ok": True,
            "title": title,
            "content": markdown,
            "data": clean_jsonable(data),
            "pushed": None,
        }
        if push:
            result["pushed"] = self.push(title, markdown)
        return result


def generate_daily_report(watchlist: Optional[List[str]] = None, push: bool = False) -> Dict:
    """便捷函数"""
    return DailyReportService(watchlist).generate(push=push)
