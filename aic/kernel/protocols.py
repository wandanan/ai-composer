"""kit/protocols.py — 协议清单（M0 最小集）。

协议 = 契约：接口签名 / 事件名 / 消息结构。实现可替换，契约稳定。
设计依据: docs/design/kernel-design.md 第四节。
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Phase(StrEnum):
    """任务阶段（首轮/追问）。"""

    FIRST = "first"          # 首轮
    FOLLOWUP = "followup"    # 追问轮


@runtime_checkable
class AgentTask(Protocol):
    """任务协议：一个业务 = 一个任务。业务插件的核心实现。"""

    id: str

    def build_system_prompt(self, ctx: Any) -> str:
        """组装系统提示词（Skill + 工具规则 + 知识范围 + 安全规则）。"""
        ...

    def toolsets(self, phase: Phase) -> list[str]:
        """主代理工具集（按阶段区分：首轮强制/追问放宽）。"""
        ...

    def knowledge_scope(self, meta: dict) -> list[str]:
        """知识注入范围。"""
        ...

    def on_result(self, session: Any, result: Any) -> Any:
        """结果处理（报告提取/产物生成/版本管理）。"""
        ...


@runtime_checkable
class ToolHandler(Protocol):
    """业务工具协议：Hermes 注册协议 + 权限标记。"""

    name: str
    toolset: str
    schema: dict

    def handle(self, args: dict, **kw: Any) -> str:
        """工具执行，返回给 LLM 的结果文本。"""
        ...


@runtime_checkable
class KnowledgeProvider(Protocol):
    """知识注入协议（规范/模板/范例）。"""

    def scope(self, task_id: str, meta: dict) -> list[str]:
        """按任务与元数据筛选知识范围。"""
        ...


@runtime_checkable
class AgentLoop(Protocol):
    """Agent 引擎协议：hermes / 假引擎 / 未来任何引擎实现它，经 ctx.agentLoop 接入。

    消费者纪律: 每次调用时 ctx.get("agentLoop")，不缓存引用 → 引擎可任意替换。
    """

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
