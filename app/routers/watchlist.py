"""
自选股 API 路由
"""
import json
from fastapi import APIRouter, Query, UploadFile, File
from fastapi.responses import JSONResponse

from app.dependencies import get_raw_fetcher, get_stock_manager

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("")
async def get_watchlist():
    """获取自选股列表（含实时行情）"""
    mgr = get_stock_manager()
    try:
        stocks = mgr.get_watchlist_with_quotes()
        return {"stocks": stocks, "count": len(stocks)}
    except Exception as e:
        # 兜底：返回不带行情的列表
        wl = mgr.load_watchlist()
        return {"stocks": wl.get("stocks", []), "count": wl.get("count", 0), "error": str(e)}


@router.post("/add")
async def add_to_watchlist(
    codes: str = Query(..., description="逗号分隔的股票代码"),
    names: str = Query("", description="逗号分隔的股票名称，与 codes 一一对应"),
):
    """添加自选股"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    names_list = [n.strip() for n in names.split(",") if n.strip()] if names else []
    # 构造 {code: name} 映射
    names_dict = {}
    for i, code in enumerate(code_list):
        if i < len(names_list) and names_list[i]:
            names_dict[code] = names_list[i]

    mgr = get_stock_manager()
    result = mgr.add_to_watchlist(code_list, names=names_dict)

    # 返回更新后的自选股
    stocks = mgr.load_watchlist()
    return {"message": "添加成功", "stocks": stocks.get("stocks", []), "count": stocks.get("count", 0)}


@router.post("/remove")
async def remove_from_watchlist(codes: str = Query(..., description="逗号分隔的股票代码")):
    """移除自选股"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    mgr = get_stock_manager()
    result = mgr.remove_from_watchlist(code_list)

    stocks = mgr.load_watchlist()
    return {"message": "移除成功", "stocks": stocks.get("stocks", []), "count": stocks.get("count", 0)}


@router.get("/export")
async def export_watchlist():
    """导出自选股 JSON"""
    mgr = get_stock_manager()
    wl = mgr.load_watchlist()
    return JSONResponse(content=wl, headers={
        "Content-Disposition": "attachment; filename=watchlist.json"
    })


@router.post("/import")
async def import_watchlist(file: UploadFile = File(...)):
    """导入自选股 JSON"""
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"无效的JSON文件: {e}")
    if not isinstance(data, dict) or "stocks" not in data:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="JSON文件格式不符，需包含 'stocks' 字段")
    mgr = get_stock_manager()
    mgr.save_watchlist(data.get("stocks", []))

    stocks = mgr.load_watchlist()
    return {"message": "导入成功", "stocks": stocks.get("stocks", []), "count": stocks.get("count", 0)}
