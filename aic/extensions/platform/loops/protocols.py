"""aic.extensions.platform.loops.protocols — 引擎协议（0.2.1 内核零 AI）。

AgentLoop 引擎协议跟随引擎实现同包（fake/openai/failover/hermes 适配器就在旁边）——
内核零 AI: kernel 不承载任何引擎/AI 协议形状。

消费纪律: 每次调用时 ctx.get("agentLoop")，不缓存引用 → 引擎可任意替换。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentLoop(Protocol):
    """Agent 引擎协议：hermes / 假引擎 / 未来任何引擎实现它，经 ctx.agentLoop 接入。"""

    def run_conversation(
        self,
        user_message: str,
        conversation_history: list | None = None,
        **kw: Any,
    ) -> dict:
        """执行一轮对话，返回 {final_response, messages, token_usage, ...}。"""
        ...

    def close(self) -> None:
        """释放引擎资源。"""
        ...
