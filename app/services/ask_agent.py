"""
AI 问股引擎（v4 P1）—— 基于策略 YAML + DeepSeek 的单股诊断
====================================================================
架构借鉴 daily_stock_analysis（见 references/dsa-agent-architecture.md）：
  - 策略 = YAML 声明（strategies/*.yaml：instructions 注入 system prompt）
  - 数据 = 复用 ops_stock_detail 装配（K线+三维信号+估值+交易计划+威科夫），
          避免与现有分析引擎重复实现
  - LLM = DeepSeek 直连（function-calling 由服务端先装配数据、再单轮生成，
          无复杂 ReAct 循环 —— 单股诊断工具集固定，无需多轮工具调用）

env：DEEPSEEK_API_KEY（无 key 时返回确定性模板诊断，不编造）
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from utils.logger import logger

STRATEGY_DIR = Path(__file__).parent.parent.parent / "strategies"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_URL = "https://api.deepseek.com/chat/completions"
LLM_MODEL = os.environ.get("MEGOO_LLM_MODEL", "deepseek-v4-flash")

# ponytail: 内存缓存 YAML 策略（热重载需重启；策略少、改动低频，够用）
_strategies: Optional[Dict[str, Dict]] = None


def _load_yaml(path: Path) -> Optional[Dict]:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"策略 YAML 解析失败 {path.name}: {e}")
        return None


def load_strategies() -> Dict[str, Dict]:
    """扫描 strategies/ 目录，返回 {name: strategy}"""
    global _strategies
    if _strategies is not None:
        return _strategies
    result = {}
    if STRATEGY_DIR.exists():
        for f in sorted(STRATEGY_DIR.glob("*.yaml")):
            s = _load_yaml(f)
            if s and s.get("name"):
                result[s["name"]] = s
    _strategies = result
    return result


def resolve_strategy(text: str) -> Dict:
    """按别名匹配策略；无匹配返回默认 comprehensive"""
    strategies = load_strategies()
    if not strategies:
        return {}
    text = (text or "").lower()
    # 1. 显式策略名点名
    for s in strategies.values():
        if s.get("name") and str(s["name"]).lower() == text.strip().lower():
            return s
    # 2. 别名命中
    for s in strategies.values():
        for alias in s.get("aliases", []):
            if alias and str(alias).lower() in text:
                return s
    return strategies.get("comprehensive", next(iter(strategies.values()), {}))


# ───────────────────────── 数据装配 ─────────────────────────

def _collect_stock_data(code: str) -> Dict:
    """复用 ops_stock_detail 的装配逻辑拿真实数据（含降级容错）"""
    from app.routers.ops import ops_stock_detail
    try:
        return ops_stock_detail(code)
    except Exception as e:
        logger.warning(f"问股数据装配失败 {code}: {e}")
        return {"code": code, "error": str(e)}


def _summarize_data(detail: Dict, max_len: int = 6000) -> str:
    """把详情 dict 压成 LLM 可读的紧凑文本"""
    if not detail:
        return "（无数据）"
    if detail.get("error"):
        return f"数据获取失败: {detail['error']}"
    code = detail.get("code", "")
    name = detail.get("name", code)
    price = detail.get("price", "-")
    lines = [f"股票: {name}({code})  现价: {price}元"]
    decision = detail.get("decision") or {}
    if decision:
        lt = decision.get("long_term") or {}
        sw = decision.get("swing") or {}
        st = decision.get("short_term") or {}
        lines.append(f"三维决策: 长线{lt.get('signal', '-')} "
                     f"波段{sw.get('signal', '-')} "
                     f"短线{st.get('signal', '-')} "
                     f"综合分{decision.get('composite_score', '-')} 动作{decision.get('action', '-')}")
    plan = detail.get("plan") or {}
    if plan:
        lines.append(f"评级: {plan.get('rating', '-')}  建议: {plan.get('action', '-')}  "
                     f"入场 {plan.get('entry_low', '-')}~{plan.get('entry_high', '-')}  "
                     f"目标 {plan.get('target_price', '-')}  止损 {plan.get('stop_loss', '-')}  "
                     f"仓位 {plan.get('position_pct', '-')}%")
    val = detail.get("valuation") or {}
    if val:
        lines.append(f"估值: PE分位{val.get('pe_pct', '-')}%  PB分位{val.get('pb_pct', '-')}%  "
                     f"区间: {val.get('zone_cn', val.get('zone', '-'))}")
    text = "\n".join(lines)
    return text[:max_len]


# ───────────────────────── LLM 诊断 ─────────────────────────

def ask(code: str, question: str = "", strategy_name: str = "",
        with_llm: bool = True) -> Dict:
    """问股主入口：装配数据 → 选定策略 → DeepSeek 诊断。

    返回 {code, name, strategy, deterministic, answer, data_summary}
    deterministic=True 表示无 LLM key 走了模板。
    """
    strategies = load_strategies()
    strategy = strategies.get(strategy_name) if strategy_name else resolve_strategy(question)
    detail = _collect_stock_data(code)
    summary = _summarize_data(detail)
    name = detail.get("name", code)
    strategy_disp = (strategy or {}).get("display_name", "综合诊断")

    if not with_llm or not DEEPSEEK_API_KEY:
        return {
            "code": code, "name": name, "strategy": strategy_disp,
            "deterministic": True, "answer": _fallback_answer(detail),
            "data_summary": summary,
        }

    instructions = (strategy or {}).get("instructions", "")
    user_q = (question or "请综合诊断这只股票现在能不能买/持有/卖").strip()
    prompt = (
        f"{instructions}\n\n"
        f"用户问题：{user_q}\n\n"
        f"以下是该股票的真实分析数据（禁止编造数据之外的数字）：\n{summary}"
    )
    try:
        resp = requests.post(
            LLM_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "你输出简体中文投资诊断，专业、克制、不承诺收益。"},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 3000,
                "temperature": 0.5,
            },
            timeout=90,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return {
            "code": code, "name": name, "strategy": strategy_disp,
            "deterministic": False, "answer": content or "（模型返回空）",
            "data_summary": summary,
        }
    except Exception as e:
        logger.error(f"问股 LLM 调用失败: {e}")
        return {
            "code": code, "name": name, "strategy": strategy_disp,
            "deterministic": True, "error": str(e),
            "answer": _fallback_answer(detail) + f"\n\n（LLM 调用失败: {e}）",
            "data_summary": summary,
        }


def _fallback_answer(detail: Dict) -> str:
    """无 LLM key / 调用失败时的确定性模板诊断（基于真实评级，不编造）"""
    plan = detail.get("plan") or {}
    decision = detail.get("decision") or {}
    rating = plan.get("rating", "-")
    action = plan.get("action", "观望")
    price = plan.get("price", "-")
    name = detail.get("name", detail.get("code", ""))
    return (
        f"**{name} 确定性诊断**（未配置 LLM，基于本地分析引擎）\n\n"
        f"评级 **{rating}** ｜ 建议 **{action}** ｜ 现价 {price} 元\n\n"
        f"入场区间 {plan.get('entry_low', '-')}~{plan.get('entry_high', '-')}，"
        f"目标 {plan.get('target_price', '-')}，止损 {plan.get('stop_loss', '-')}，"
        f"建议仓位 {plan.get('position_pct', '-')}%\n\n"
        f"三维决策：长线{decision.get('long_term', {}).get('signal', '-')} / "
        f"波段{decision.get('swing', {}).get('signal', '-')} / "
        f"短线{decision.get('short_term', {}).get('signal', '-')}\n\n"
        f"⚠️ 非投资建议。配置 DEEPSEEK_API_KEY 可获得 AI 深度解读。"
    )
