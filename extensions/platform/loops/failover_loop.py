"""kit/loops/failover_loop.py — 引擎降级适配器（M4）。

主引擎失败时自动降级到备用引擎（如 API 故障 → 确定性假引擎兜底）。
演示平台级"降级矩阵"在引擎维度的实现：消费方无感（仍是 ctx.agentLoop）。
"""
from __future__ import annotations

from typing import Any


class FailoverLoop:
    """主引擎失败 → 备用引擎。记录降级次数。"""

    name = "failover"

    def __init__(self, primary: Any, fallback: Any):
        self._primary = primary
        self._fallback = fallback
        self.fallbacks = 0

    def run_conversation(
        self,
        user_message: str,
        conversation_history: list | None = None,
        **kw: Any,
    ) -> dict:
        try:
            return self._primary.run_conversation(
                user_message, conversation_history, **kw)
        except Exception:
            self.fallbacks += 1
            return self._fallback.run_conversation(
                user_message, conversation_history, **kw)

    def close(self) -> None:
        for loop in (self._primary, self._fallback):
            close = getattr(loop, "close", None)
            if close is not None:
                close()
