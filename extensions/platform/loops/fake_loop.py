"""kit/loops/fake_loop.py — 假引擎（确定性输出，不依赖 LLM）。

用途：
- 协议验证：在接入真实 Hermes 之前验证 ctx.agentLoop 协议与消费方
- 测试：流水线/插件逻辑的确定性单测
- 离线开发：没有 API 密钥时也能跑通业务编排
"""
from __future__ import annotations

import threading
import time
from typing import Any


class FakeLoop:
    """确定性 Agent 引擎：按关键词命中回复表，记录每次调用。

    附带并发追踪（max_concurrent）：验证并行章节编写等并发场景。
    delay > 0 时模拟耗时（真实 LLM 的延迟），使并发可被观测——
    任务太短时 GIL 切换间隔（~5ms）远大于任务时长，并发会被串行化。
    """

    def __init__(self, name: str = "fake-loop", replies: dict[str, str] | None = None,
                 delay: float = 0.0):
        self.name = name
        self._replies = replies or {}
        self._delay = delay
        self.calls: list[dict] = []
        self.max_concurrent = 0
        self._lock = threading.Lock()
        self._active = 0

    def run_conversation(
        self,
        user_message: str,
        conversation_history: list | None = None,
        **kw: Any,
    ) -> dict:
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            if self._delay:
                time.sleep(self._delay)
            self.calls.append({"message": user_message, "history": conversation_history})

            text = None
            for keyword, reply in self._replies.items():
                if keyword in user_message:
                    text = reply
                    break
            if text is None:
                text = f"[{self.name}] 未命中回复表: {user_message[:40]}"

            return {
                "final_response": text,
                "messages": [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": text},
                ],
                "token_usage": {"input_tokens": 10, "output_tokens": len(text)},
            }
        finally:
            with self._lock:
                self._active -= 1

    def close(self) -> None:
        self.calls.append({"closed": True})
