"""异步任务结果磁盘持久化 —— 重启后回测/排行/三把锁结果不丢
================================================================
各任务服务把终态(done/error)写 JSON 到 cache_data/{name}_tasks.json，
服务重启 __init__ 时载入，前端 status/result 接口依旧可用。
文件小、任务量少：写全量即可；只保留最近 _KEEP_DONE 个终态防膨胀。
"""
import json
from pathlib import Path

from utils.logger import logger

_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache_data"
_KEEP_DONE = 30


def _path(name: str) -> Path:
    return _CACHE_DIR / f"{name}_tasks.json"


def load_tasks(name: str) -> dict:
    p = _path(name)
    try:
        if p.exists():
            tasks = json.loads(p.read_text(encoding="utf-8"))
            # 上次进程崩溃残留的 running 任务 → 标记中断，避免前端永远转圈
            for k, v in list(tasks.items()):
                if v.get("status") == "running":
                    tasks[k] = {
                        "status": "error", "error": "服务重启，任务中断",
                        "progress": v.get("progress", 0), "step": "中断",
                    }
            return tasks
    except Exception as e:
        logger.warning(f"任务持久化读取失败 {p.name}: {e}")
    return {}


def save_tasks(name: str, tasks: dict) -> None:
    try:
        done = [k for k, v in tasks.items() if v.get("status") in ("done", "error")]
        if len(done) > _KEEP_DONE:
            for k in done[:-_KEEP_DONE]:
                tasks.pop(k, None)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _path(name)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        logger.debug(f"任务持久化写入失败: {e}")
