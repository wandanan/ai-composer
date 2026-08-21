"""kit/stream — SSE 进度推送（ctx.stream 插件）。

把内核事件桥接为客户端可消费的 SSE 流：
- 事件源: pipeline/phase、chapter/status、pipeline/done（事件 payload 携带 aic_session_id）
- 双通道: in-process 队列（线程路径）+ Redis pub/sub（Celery worker 跨进程路径）
"""
from .sse import StreamPlugin, StreamService

__all__ = ["StreamPlugin", "StreamService"]
