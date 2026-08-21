"""kit/base/telemetry.py — 遥测基础设施插件（M4b）。

ctx.telemetry: 事件/日志/统计的统一出口。对应 app/base/logger + tracing 的插件化。
"""
from __future__ import annotations

from typing import Callable

from aic.kernel import Context, Plugin


class TelemetryService:
    """遥测服务（ctx.telemetry）。"""

    _MAX_EVENTS = 10_000   # 环形缓冲上限: 长跑进程 events 无界增长会泄漏内存

    def __init__(self, sink: Callable[[str], None] | None = None):
        self._sink = sink or (lambda msg: print(f"[telemetry] {msg}"))
        self.events: list[tuple] = []

    def trace(self, event: str, **fields) -> None:
        """记录一次事件（含结构化字段），并写入事件列表供断言。"""
        self.events.append((event, fields))
        if len(self.events) > self._MAX_EVENTS:
            del self.events[:len(self.events) - self._MAX_EVENTS]
        self._sink(f"{event} {fields}")

    def log(self, level: str, message: str) -> None:
        self.trace(f"log/{level}", message=message)


class TelemetryPlugin(Plugin):
    """遥测插件：提供 ctx.telemetry。"""

    provides = ["telemetry"]

    def apply(self, ctx: Context):
        ctx.register("telemetry", TelemetryService())
