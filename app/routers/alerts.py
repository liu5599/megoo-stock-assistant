"""
股价预警 API —— /api/alerts
规则管理（增删改查）+ 手动跑一次 + 查询命中历史
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.services import price_alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/rules")
def list_rules() -> Dict:
    """全部预警规则"""
    return {"rules": price_alert.load_rules(), "types": price_alert.RULE_TYPES}


@router.post("/rules")
def create_rule(code: str = Query(..., description="股票代码"),
                name: str = Query("", description="股票名称"),
                rule_type: str = Query(..., description="规则类型"),
                value: float = Query(..., gt=0, description="阈值"),
                enabled: bool = Query(True)) -> Dict:
    try:
        rule = price_alert.add_rule(code, name, rule_type, value, enabled)
        return {"ok": True, "rule": rule}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/rules")
def delete_rule(code: str = Query(...),
                rule_type: str = Query(...),
                value: float = Query(...)) -> Dict:
    ok = price_alert.remove_rule(code, rule_type, value)
    if not ok:
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}


@router.post("/rules/toggle")
def toggle(code: str = Query(...), rule_type: str = Query(...),
           value: float = Query(...), enabled: bool = Query(True)) -> Dict:
    ok = price_alert.toggle_rule(code, rule_type, value, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}


@router.post("/check")
def check_now() -> Dict:
    """手动跑一次全部规则（不依赖轮询线程）"""
    from data.stock_manager import StockManager
    from data.data_utils import get_best_fetcher

    mgr = StockManager(fetcher=get_best_fetcher())
    rows = mgr.get_watchlist_with_quotes()
    quotes_map = {}
    for row in rows:
        q = row.get("quote")
        if q is not None:
            quotes_map[str(row.get("code", "")).zfill(6)] = q
    hits = price_alert.check_once(quotes_map)
    return {"ok": True, "checked": len(quotes_map), "hits": [
        {"code": h["rule"].get("code"), "name": h["rule"].get("name"),
         "type": h["rule"].get("type"), "value": h["rule"].get("value"),
         "price": h["quote_price"], "pct": h["pct"], "time": h["time"]}
        for h in hits
    ]}


@router.post("/start")
def start() -> Dict:
    price_alert.start_alert_thread()
    return {"ok": True, "running": True}


@router.post("/stop")
def stop() -> Dict:
    price_alert.stop_alert_thread()
    return {"ok": True, "running": False}
