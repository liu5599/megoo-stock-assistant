"""
轻量 TTL 缓存 —— 给慢速数据源（akshare）加内存缓存
================================================
akshare 每次调用 3-15s，重复请求直接命中缓存，大幅降低等待。

Stale-While-Revalidate 模式（默认开启）：
  缓存过期时立即返回旧数据（用户秒开），同时后台线程刷新新数据。
  彻底消除"冷加载 18-30s"的等待。
"""
import threading
import time
from functools import wraps

_CACHE: dict = {}
_REFRESHING: set = set()  # 正在后台刷新的 key，防并发重复刷新
_LOCK = threading.Lock()


def _start_refresh(fn, key, args, kwargs):
    """后台刷新缓存（防并发：同一 key 只允许一个刷新任务）"""
    with _LOCK:
        if key in _REFRESHING:
            return
        _REFRESHING.add(key)

    def _do():
        try:
            result = fn(*args, **kwargs)
            if result is not None:
                _CACHE[key] = (time.time(), result)
        finally:
            _REFRESHING.discard(key)

    threading.Thread(target=_do, daemon=True).start()


def ttl_cache(ttl_seconds: int = 300, swr: bool = True):
    """TTL 内存缓存装饰器（不缓存 None/空结果，避免缓存失败态）

    Args:
        ttl_seconds: 缓存有效期（秒）
        swr: 过期时 stale-while-revalidate（返回旧值 + 后台刷新）
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__name__, repr(args), repr(sorted(kwargs.items())))
            now = time.time()
            hit = _CACHE.get(key)

            # 缓存新鲜 → 直接返回
            if hit and now - hit[0] < ttl_seconds:
                return hit[1]

            # 缓存过期但存在 → SWR：返回旧值 + 后台刷新
            if swr and hit:
                _start_refresh(fn, key, args, kwargs)
                return hit[1]

            # 无缓存 → 冷加载（首次）
            result = fn(*args, **kwargs)
            if result is not None:
                _CACHE[key] = (now, result)
            return result

        return wrapper

    return deco


def clear_cache():
    """清空全部缓存（调试/测试用）"""
    _CACHE.clear()
