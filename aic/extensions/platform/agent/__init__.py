"""aic.extensions.platform.agent — AI 任务协议包（0.2.1 内核零 AI）。

AI 业务协议的归宿: 与 base/session/extract 等平台能力并列, 不进内核——
内核 = 纯机制（不认识 AI 也不认识业务）。AI 业务插件实现这些协议形状即可,
无需继承（runtime_checkable 结构校验）。
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Callable, Protocol, runtime_checkable

from aic.kernel import Context, Plugin


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


class TaskRegistry:
    """AgentTask 注册表（聚合键语义: 多业务插件共挂时各自登记, 互不覆盖）。

    与 RenderRegistry 同构: "tasks" 是多提供方聚合键, 不能用 ctx.register
    的"同 key 后注册覆盖"语义（共挂 review+writer 会互删任务字典）。
    register 返回 disposer（插件 ctx.effect 登记 → unmount 撤销自己的任务,
    同名替换可恢复——与内核 register 的 per-key 栈同语义）。
    """

    def __init__(self):
        self._tasks: dict[str, Any] = {}

    def register(self, task: Any) -> Callable[[], None]:
        """登记任务（按 task.id）, 返回 disposer（撤销; 同名替换恢复前一个）。"""
        tid = task.id
        previous = self._tasks.get(tid)
        self._tasks[tid] = task

        def _dispose():
            if previous is None:
                self._tasks.pop(tid, None)
            else:
                self._tasks[tid] = previous

        return _dispose

    def get(self, task_id: str, default: Any = None) -> Any:
        return self._tasks.get(task_id, default)

    def __getitem__(self, task_id: str) -> Any:
        return self._tasks[task_id]

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._tasks

    def ids(self) -> list[str]:
        return sorted(self._tasks)


class TasksPlugin(Plugin):
    """任务注册表插件: 提供 ctx.tasks（聚合键, 业务插件 ctx.get("tasks").register(...)）。

    业务插件声明 inject=["tasks"]（拓扑保证本插件先挂载）,
    apply 里 ctx.effect(ctx.get("tasks").register(XxxTask()))——unmount 零残留。
    """

    PUBLIC = True   # 公共插件: 模板提取时随业务插件（inject tasks）一起带走
    provides = ["tasks"]

    def apply(self, ctx: Context):
        ctx.register("tasks", TaskRegistry())


__all__ = ["AgentTask", "KnowledgeProvider", "Phase", "TaskRegistry",
           "TasksPlugin", "ToolHandler"]
