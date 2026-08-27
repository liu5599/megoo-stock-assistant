"""
信号快照存储（v3.1 P0）—— 记录系统每日输出，用于复盘与绩效统计
================================================================
SQLite 存储：每日盘面快照 / SABC 交易计划 / 三维决策信号
用途：
  - 历史回看：查询任意一天系统给过什么信号
  - 绩效统计：T+N 后验证评级/信号胜率（factor_performance）
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger import logger

_DB_PATH = Path(__file__).parent.parent / "cache_data" / "signal_snapshots.db"


def _conn():
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,      -- overview / plan / signal
                code TEXT,
                name TEXT,
                payload TEXT NOT NULL,            -- JSON
                UNIQUE(trade_date, snapshot_type, code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_snap_date ON snapshots(trade_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_snap_code ON snapshots(code)")


_init()


def save_snapshot(trade_date: str, snapshot_type: str, payload: Dict, code: str = "", name: str = "") -> bool:
    """保存一条快照（同日期同类型同代码覆盖）"""
    try:
        with _conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO snapshots
                   (trade_date, created_at, snapshot_type, code, name, payload)
                   VALUES (?,?,?,?,?,?)""",
                (trade_date, time.strftime("%Y-%m-%d %H:%M:%S"), snapshot_type, code, name,
                 json.dumps(payload, ensure_ascii=False, default=str)),
            )
        return True
    except Exception as e:
        logger.warning(f"快照保存失败: {e}")
        return False


def save_plans_snapshot(plans: List[Dict]) -> int:
    """批量保存交易计划快照（返回保存条数）"""
    trade_date = time.strftime("%Y-%m-%d")
    n = 0
    for p in plans:
        if save_snapshot(trade_date, "plan", p, p.get("code", ""), p.get("name", "")):
            n += 1
    return n


def query_snapshots(trade_date: str = "", snapshot_type: str = "", code: str = "",
                    limit: int = 100) -> List[Dict]:
    """查询快照（支持按日期/类型/代码过滤）"""
    sql = "SELECT * FROM snapshots WHERE 1=1"
    params = []
    if trade_date:
        sql += " AND trade_date=?"
        params.append(trade_date)
    if snapshot_type:
        sql += " AND snapshot_type=?"
        params.append(snapshot_type)
    if code:
        sql += " AND code=?"
        params.append(code)
    sql += f" ORDER BY id DESC LIMIT ?"
    params.append(limit)
    try:
        with _conn() as c:
            rows = c.execute(sql, params).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r[0], "trade_date": r[1], "created_at": r[2],
                "type": r[3], "code": r[4], "name": r[5],
                "payload": json.loads(r[6]),
            })
        return result
    except Exception as e:
        logger.warning(f"快照查询失败: {e}")
        return []


def latest_plan_codes(limit: int = 50) -> List[Dict]:
    """最近一次交易计划快照的评级列表（绩效统计输入）"""
    rows = query_snapshots(snapshot_type="plan", limit=limit * 5)
    by_date = {}
    for r in rows:
        d = r["trade_date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(r)
    if not by_date:
        return []
    latest_date = max(by_date.keys())
    return by_date[latest_date]


def stats() -> Dict:
    """快照库统计"""
    try:
        with _conn() as c:
            total = c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            dates = c.execute("SELECT COUNT(DISTINCT trade_date) FROM snapshots").fetchone()[0]
            types = c.execute("SELECT snapshot_type, COUNT(*) FROM snapshots GROUP BY snapshot_type").fetchall()
        return {"total": total, "dates": dates,
                "types": {t: n for t, n in types}}
    except Exception as e:
        return {"error": str(e)}
