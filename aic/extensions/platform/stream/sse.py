"""kit/stream/sse.py — SSE 进度推送插件（ctx.stream）。

职责：
- 订阅内核事件（pipeline/phase、chapter/status、pipeline/done）
- 按 session_id 路由推送给 SSE 订阅者
- 双通道：in-process 队列（同进程执行路径）+ Redis pub/sub（Celery worker 跨进程）

事件协议约定：内核事件 payload 必须携带 session_id（pipeline 已保证）。
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any

from aic.kernel import Context, EventMode, Plugin

_log = logging.getLogger(__name__)


class StreamService:
    """会话级事件推送服务（ctx.stream）。

    事件缓冲：会话事件留痕（上限 history_limit），SSE 订阅晚到时先回放——
    解决"任务快于订阅建立"的丢事件问题（原审查应用的重连回放同思路）。
    """

    def __init__(self, ctx: Context | None = None, redis_url: str | None = None,
                 history_limit: int = 200):
        self._ctx = ctx
        self.redis_url = redis_url
        self._subs: dict[str, list[queue.Queue]] = {}
        self._history: dict[str, list[dict]] = {}
        self._history_limit = history_limit
        self._lock = threading.Lock()

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)

    def bridge(self, event_name: str) -> None:
        """业务声明: 事件 → 会话推送（0.2.1 平台通道化——StreamPlugin 不认识业务事件）。

        payload 须携带 session_id（否则 publish 警告跳过）。由业务插件 apply 调用。
        """
        if self._ctx is None:
            raise RuntimeError("[stream] bridge 需要 ctx（StreamPlugin 构造注入）")
        self._ctx.on(event_name,
                     lambda p: self.publish(p.get("session_id", ""), event_name, p),
                     EventMode.EMIT)

    # ── 订阅（SSE 端点侧）──

    def subscribe(self, session_id: str) -> tuple[queue.Queue, list[dict]]:
        """订阅会话事件；返回 (实时队列, 已发生事件快照)。"""
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.setdefault(session_id, []).append(q)
            snapshot = list(self._history.get(session_id, []))
        return q, snapshot

    def unsubscribe(self, session_id: str, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subs[session_id].remove(q)
            except ValueError:
                pass

    # ── 发布（事件桥接侧）──

    def publish(self, session_id: str, event: str, data: dict) -> None:
        if not session_id:
            _log.warning("[stream] publish 跳过: 事件未携带 session_id (event=%r)", event)
            return
        payload = {"event": event, "data": data}

        # 通道 1: in-process 队列（同进程: 线程降级路径）+ 事件缓冲
        with self._lock:
            hist = self._history.setdefault(session_id, [])
            hist.append(payload)
            if len(hist) > self._history_limit:
                del hist[:len(hist) - self._history_limit]
            for q in list(self._subs.get(session_id, [])):
                q.put(payload)

        # 通道 2: Redis pub/sub（跨进程: Celery worker 路径）
        if self.redis_url:
            try:
                import redis as redis_sync
                r = redis_sync.Redis.from_url(self.redis_url,
                                              socket_connect_timeout=1)
                r.publish(f"sse:{session_id}",
                          json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass  # Redis 不可用时 in-process 兜底


class StreamPlugin(Plugin):
    """SSE 推送插件：提供 ctx.stream + 通用事件桥接（0.2.1 平台通道化）。

    StreamPlugin 不认识任何具体事件名——桥接由业务插件声明
    （`ctx.get("stream").bridge("pipeline/phase")`）; 平台零业务耦合。
    """

    provides = ["stream"]

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url

    def apply(self, ctx: Context):
        svc = StreamService(ctx, self._redis_url)
        ctx.register("stream", svc)
