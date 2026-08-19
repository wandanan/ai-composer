"""kit/base/cache.py — 缓存基础设施插件（M4b + 并发安全补强）。

ctx.cache: KV 缓存协议（set/get/set_nx, 支持 TTL）。
- MemoryCache: 内存实现（单进程验证/兜底, 线程安全）
- RedisCache:  真实 Redis 适配器（多进程共享, SET NX 原子锁）

并发安全: set_nx 是原子操作（MemoryCache 用锁, RedisCache 用 SET NX）——
多进程场景（API + Celery worker）必须配 RedisCache, 否则锁/running 各自进程内存不共享。
"""
from __future__ import annotations

import threading
import time
from typing import Protocol, runtime_checkable

from kernel import Context, Plugin


@runtime_checkable
class Cache(Protocol):
    """KV 缓存协议。"""

    def set(self, key: str, value: str, ttl: float | None = None) -> None: ...
    def get(self, key: str) -> str | None: ...
    def set_nx(self, key: str, value: str, ttl: float | None = None) -> bool:
        """原子 SET NX: 不存在则写入并返回 True; 已存在返回 False。"""
        ...
    def delete(self, key: str) -> None:
        """删除 key（释放锁用; 不能用 set('')——空串非 None, 会挡 set_nx）。"""
        ...


class MemoryCache:
    """内存缓存（线程安全, 含 TTL 过期）。"""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._expires: dict[str, float] = {}
        self._lock = threading.RLock()   # 可重入: set_nx 内再调 get() 不死锁

    def set(self, key: str, value: str, ttl: float | None = None) -> None:
        with self._lock:
            self._data[key] = value
            self._expires[key] = time.time() + ttl if ttl else None

    def get(self, key: str) -> str | None:
        with self._lock:
            exp = self._expires.get(key)
            if exp is not None and time.time() > exp:
                self._data.pop(key, None)
                self._expires.pop(key, None)
                return None
            return self._data.get(key)

    def set_nx(self, key: str, value: str, ttl: float | None = None) -> bool:
        with self._lock:
            if self.get(key) is not None:
                return False
            self._data[key] = value
            self._expires[key] = time.time() + ttl if ttl else None
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._expires.pop(key, None)


class RedisCache:
    """真实 Redis 适配器（多进程共享; SET NX 原子锁; TTL 过期）。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 6379, db: int = 0,
                 url: str | None = None):
        import redis as redis_sync
        if url:
            self._r = redis_sync.Redis.from_url(url, socket_connect_timeout=1)
        else:
            self._r = redis_sync.Redis(host=host, port=port, db=db,
                                       socket_connect_timeout=1)

    def set(self, key: str, value: str, ttl: float | None = None) -> None:
        self._r.set(key, value, ex=int(ttl) if ttl else None)

    def get(self, key: str) -> str | None:
        v = self._r.get(key)
        return v.decode("utf-8") if v else None

    def set_nx(self, key: str, value: str, ttl: float | None = None) -> bool:
        return bool(self._r.set(key, value, ex=int(ttl) if ttl else None, nx=True))

    def delete(self, key: str) -> None:
        self._r.delete(key)


class CachePlugin(Plugin):
    """缓存插件：提供 ctx.cache。构造注入实现（默认 MemoryCache, 可注 RedisCache）。"""

    provides = ["cache"]

    def __init__(self, impl: Cache | None = None):
        self._impl = impl

    def apply(self, ctx: Context):
        ctx.register("cache", self._impl or MemoryCache())
