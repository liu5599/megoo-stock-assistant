"""
AI 问股 API —— /api/ask
POST /api/ask          同步问股（单轮诊断）
GET  /api/ask/strategies  列出可用策略
"""
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services import ask_agent

router = APIRouter(prefix="/ask", tags=["ask"])


@router.get("/strategies")
def list_strategies() -> Dict:
    """列出可用问股策略"""
    strategies = ask_agent.load_strategies()
    return {"strategies": [
        {"name": s.get("name"), "display_name": s.get("display_name"),
         "category": s.get("category", ""), "aliases": s.get("aliases", [])}
        for s in strategies.values()
    ]}


@router.post("")
def ask(code: str = Query(..., description="股票代码，如 600519"),
        question: str = Query("", description="用户问题/别名，如 威科夫/综合诊断"),
        strategy: str = Query("", description="显式策略名，空则按问题自动路由"),
        with_llm: bool = Query(True)) -> Dict:
    try:
        result = ask_agent.ask(code, question=question,
                               strategy_name=strategy, with_llm=with_llm)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/decide")
def decide(code: str = Query(..., description="股票代码"),
           question: str = Query("", description="用户问题"),
           strategy: str = Query(""),
           with_llm: bool = Query(True),
           total_position: float = Query(0.0, description="当前总仓位 0-1"),
           single_ratio: float = Query(0.0, description="该票当前占比 0-1"),
           regime: str = Query("", description="大盘 regime，如 防守/进攻"),
           total_capital: float = Query(1000000.0)) -> Dict:
    """结构化决策：LLM 出 JSON 指令 → 强制过风控闸 → 可执行决策"""
    portfolio = {
        "total_position": total_position,
        "total_capital": total_capital,
        "positions": {code: {"ratio": single_ratio}} if single_ratio else {},
    }
    market = {"regime": regime} if regime else {}
    try:
        result = ask_agent.decide(code, question=question, strategy_name=strategy,
                                  portfolio=portfolio, market=market, with_llm=with_llm)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reflect")
def reflect(horizon: int = Query(10, description="回看窗口(交易日)"),
            with_llm: bool = Query(True)) -> Dict:
    """跑一次 AI 复盘反思（读决策账本 → LLM 反思 → 存 memory/reflection.md）"""
    from app.services import reflection
    try:
        return {"ok": True, **reflection.reflect(horizon_days=horizon, with_llm=with_llm)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reflection")
def get_reflection() -> Dict:
    """读取最近一次复盘反思"""
    from app.services import reflection
    text = reflection.load_reflection()
    return {"ok": True, "has_reflection": bool(text), "content": text}


@router.post("/stream")
def ask_stream(code: str = Query(..., description="股票代码"),
               question: str = Query("", description="用户问题"),
               strategy: str = Query("")) -> StreamingResponse:
    """SSE 流式问股：先回数据摘要，再逐字流 LLM 回答"""
    def gen():
        try:
            yield _sse("meta", {"code": code, "strategy": strategy or question})
            strategies = ask_agent.load_strategies()
            s = strategies.get(strategy) if strategy else ask_agent.resolve_strategy(question)
            detail = ask_agent._collect_stock_data(code)
            summary = ask_agent._summarize_data(detail)
            yield _sse("data", {"summary": summary})
            if not ask_agent.DEEPSEEK_API_KEY:
                yield _sse("answer", {"answer": ask_agent._fallback_answer(detail),
                                      "deterministic": True})
                yield _sse("done", {})
                return
            instructions = (s or {}).get("instructions", "")
            user_q = (question or "请综合诊断这只股票").strip()
            prompt = f"{instructions}\n\n用户问题：{user_q}\n\n真实数据：\n{summary}"
            import requests as _r
            resp = _r.post(
                ask_agent.LLM_URL,
                headers={"Authorization": f"Bearer {ask_agent.DEEPSEEK_API_KEY}"},
                json={"model": ask_agent.LLM_MODEL,
                      "messages": [
                          {"role": "system", "content": "你输出简体中文投资诊断，专业克制。"},
                          {"role": "user", "content": prompt}],
                      "max_tokens": 3000, "temperature": 0.5,
                      "stream": True},
                timeout=120, stream=True,
            )
            resp.raise_for_status()
            buffer = []
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                except Exception:
                    continue
                if delta:
                    buffer.append(delta)
                    yield _sse("delta", {"delta": delta})
            yield _sse("answer", {"answer": "".join(buffer), "deterministic": False})
            yield _sse("done", {})
        except Exception as e:
            yield _sse("error", {"error": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
