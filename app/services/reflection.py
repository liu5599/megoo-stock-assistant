"""
AI 复盘反思（v4.1 P1）—— 从决策账本学习，形成进化闭环
====================================================================
评审缺陷四：AI 每次调用独立，不知道一个月前推荐了什么、现在涨跌多少，
无法从错误中学习。

本模块：
  1. 读 snapshot_store 历史交易计划（含评级/动作/基准价）→ 拉真实收盘价算实际表现
  2. 挑出「判断偏差最大」的样本（如推荐买入却大跌）
  3. 交 LLM 反思：当时遗漏了什么风险信号？下次如何修正？
  4. 反思结论文本存入 memory/reflection.md，下次问股注入上下文

env：DEEPSEEK_API_KEY（无 key 时生成确定性统计复盘，不编造）
"""
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from utils.logger import logger

MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"
REFLECTION_FILE = MEMORY_DIR / "reflection.md"
MAX_REFLECTION_CHARS = 1500  # 注入上下文时的截断上限
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_URL = "https://api.deepseek.com/chat/completions"
LLM_MODEL = os.environ.get("MEGOO_LLM_MODEL", "deepseek-v4-flash")


def _evaluate_snapshots(horizon_days: int = 10, limit: int = 30) -> List[Dict]:
    """读历史计划快照 → 用真实收盘价算实际表现"""
    from analysis import snapshot_store
    rows = snapshot_store.query_snapshots(snapshot_type="plan", limit=limit)
    if not rows:
        return []
    from data.data_utils import get_best_fetcher
    fetcher = get_best_fetcher()
    out = []
    for r in rows:
        p = r.get("payload", {})
        code = r.get("code", "")
        base_price = p.get("price") or p.get("entry_low")
        if not code or not base_price:
            continue
        try:
            kl = fetcher.get_history_kline(
                code, "daily",
                time.strftime("%Y%m%d", time.localtime(time.time() - 60 * 86400)),
                time.strftime("%Y%m%d"), "qfq")
            if kl is None:
                continue
            df = getattr(kl, "df", kl)
            if df is None or df.empty:
                continue
            close_now = float(df["close"].iloc[-1])
            if close_now <= 0:
                continue
            ret = (close_now / float(base_price) - 1) * 100
            out.append({
                "trade_date": r.get("trade_date", ""),
                "code": code,
                "name": r.get("name", code),
                "rating": p.get("rating", "-"),
                "action": p.get("action", "-"),
                "base_price": float(base_price),
                "close_now": close_now,
                "return_pct": round(ret, 2),
            })
        except Exception as e:
            logger.debug(f"反思评估 {code} 失败: {e}")
    return out


def _pick_lessons(samples: List[Dict], top: int = 5) -> Dict:
    """挑出最值得反思的样本：买入却大跌 / 高评级却跑输"""
    buys = [s for s in samples if s["action"] in ("买入", "加仓", "买入/试仓", "持有/试仓")]
    # 买入类按收益升序（最差在前）
    buys_sorted = sorted(buys, key=lambda x: x["return_pct"])
    worst = buys_sorted[:top]
    sa = [s for s in samples if s["rating"] in ("S", "A")]
    sa_worst = sorted(sa, key=lambda x: x["return_pct"])[:top]
    stats = {
        "total": len(samples),
        "buy_count": len(buys),
        "buy_win_rate": round(sum(1 for s in buys if s["return_pct"] > 0) / len(buys) * 100, 1) if buys else 0,
        "buy_avg_return": round(sum(s["return_pct"] for s in buys) / len(buys), 2) if buys else 0,
    }
    return {"stats": stats, "worst_buys": worst, "worst_sa": sa_worst}


def reflect(horizon_days: int = 10, with_llm: bool = True) -> Dict:
    """跑一次复盘，返回 {stats, reflection, samples, path}"""
    samples = _evaluate_snapshots(horizon_days=horizon_days)
    if not samples:
        return {"available": False, "msg": "无历史计划快照（先通过 /api/ops/plan 生成）"}

    lessons = _pick_lessons(samples)
    stats = lessons["stats"]

    def _fmt(items):
        return "\n".join(
            f"- {s['trade_date']} {s['name']}({s['code']}) 评级{s['rating']} {s['action']}"
            f" 基准{s['base_price']:.2f}→现{s['close_now']:.2f} 实际{s['return_pct']:+.2f}%"
            for s in items) or "（无）"

    material = (
        f"决策账本统计：共 {stats['total']} 条计划，买入类 {stats['buy_count']} 条，"
        f"买入胜率 {stats['buy_win_rate']}%，平均收益 {stats['buy_avg_return']}%\n\n"
        f"表现最差的买入样本：\n{_fmt(lessons['worst_buys'])}\n\n"
        f"表现最差的 S/A 级样本：\n{_fmt(lessons['worst_sa'])}"
    )

    reflection = ""
    if with_llm and DEEPSEEK_API_KEY:
        prompt = (
            "你是A股私募操盘手的复盘教练。下面是你过去一段时间的交易计划与实际结果对比。"
            "请用老兵口吻写一段复盘，直指要害：\n"
            "1. 从最差样本里，总结2-3个共性失误（如：在情绪高潮追高、忽视缩量背离、低估板块退潮）\n"
            "2. 给出2-3条下次必须修正的纪律（可执行、可检验）\n"
            "3. 不超过250字，禁止套话，禁止编造统计里没有的数据\n\n" + material
        )
        try:
            resp = requests.post(
                LLM_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={"model": LLM_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 3000, "temperature": 0.6},
                timeout=90,
            )
            resp.raise_for_status()
            reflection = resp.json()["choices"][0]["message"]["content"] or ""
        except Exception as e:
            logger.error(f"复盘 LLM 失败: {e}")

    if not reflection:
        reflection = (
            f"【确定性复盘】买入类计划 {stats['buy_count']} 条，胜率 {stats['buy_win_rate']}%，"
            f"平均收益 {stats['buy_avg_return']}%。最差样本："
            + ("；".join(f"{s['name']} {s['return_pct']:+.2f}%" for s in lessons['worst_buys'][:3]) or "无")
            + "。建议核查：追高买入、忽略板块退潮、止损纪律执行。"
        )

    text = (
        f"# AI 复盘反思\n\n"
        f"> 更新：{time.strftime('%Y-%m-%d %H:%M:%S')} ｜ 回看窗口 {horizon_days} 日\n\n"
        f"## 统计\n{stats}\n\n## 复盘\n{reflection}\n"
    )
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    REFLECTION_FILE.write_text(text, encoding="utf-8")
    logger.info(f"📝 复盘反思已写入 {REFLECTION_FILE}")

    return {"available": True, "stats": stats, "reflection": reflection,
            "samples": samples, "path": str(REFLECTION_FILE)}


def load_reflection() -> str:
    """读取最近一次反思（供问股注入上下文）"""
    try:
        if REFLECTION_FILE.exists():
            return REFLECTION_FILE.read_text(encoding="utf-8")[:MAX_REFLECTION_CHARS]
    except Exception:
        pass
    return ""
