"""aic.extensions.platform.agent — AI 任务协议包（0.2.1 内核零 AI）。

AI 业务协议的归宿: 与 base/session/extract 等平台能力并列, 不进内核——
内核 = 纯机制（不认识 AI 也不认识业务）。AI 业务插件实现这些协议形状即可,
无需继承（runtime_checkable 结构校验）。
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


__all__ = ["AgentTask", "KnowledgeProvider", "Phase", "ToolHandler"]
