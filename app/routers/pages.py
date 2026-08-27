"""
页面路由 — 渲染 HTML 页面
"""
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.dependencies import get_config, get_stock_manager

router = APIRouter()

# Jinja2 模板引擎
from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


def render(template_name: str, context: dict = None) -> HTMLResponse:
    """渲染 Jinja2 模板"""
    template = jinja_env.get_template(template_name)
    html = template.render(**(context or {}))
    return HTMLResponse(content=html)


@router.get("/", response_class=HTMLResponse)
async def index():
    return render("dashboard.html", {"active_page": "dashboard"})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return render("dashboard.html", {"active_page": "dashboard"})


@router.get("/ranking", response_class=HTMLResponse)
async def ranking_page():
    return render("ranking.html", {"active_page": "ranking"})


@router.get("/stock/{code}", response_class=HTMLResponse)
async def stock_page(code: str):
    """个股详情页"""
    try:
        from app.dependencies import get_raw_fetcher
        fetcher = get_raw_fetcher()
        name = fetcher.get_stock_name(code)
    except Exception:
        name = code
    return render("stock_detail.html", {
        "active_page": "",
        "code": code,
        "name": name or code,
    })


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page():
    return render("backtest.html", {"active_page": "backtest"})


@router.get("/ops", response_class=HTMLResponse)
async def ops_page():
    """职业经理人操盘台"""
    codes = ""
    try:
        import json as _json
        from pathlib import Path as _Path
        wl_path = _Path(__file__).parent.parent.parent / "watchlist" / "default_watchlist.json"
        if wl_path.exists():
            wl = _json.loads(wl_path.read_text(encoding="utf-8"))
            codes = ",".join([s.get("code", "") for s in wl.get("stocks", [])])
    except Exception:
        pass
    return render("ops.html", {"active_page": "ops", "watchlist_codes": codes})


@router.get("/lhb", response_class=HTMLResponse)
async def lhb_page():
    """龙虎榜完整页（免费东财源）"""
    return render("lhb.html", {"active_page": "ops"})


@router.get("/theme/{name}", response_class=HTMLResponse)
async def theme_detail_page(name: str):
    """题材详情页（第二层钻取）"""
    return render("theme_detail.html", {"active_page": "ops", "board_name": name})


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page():
    return render("watchlist.html", {"active_page": "watchlist"})


@router.get("/surge", response_class=HTMLResponse)
async def surge_page():
    return render("surge.html", {"active_page": "surge"})


@router.get("/compare", response_class=HTMLResponse)
async def compare_page():
    return render("compare.html", {"active_page": "compare"})
