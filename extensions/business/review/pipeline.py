"""review/pipeline.py — ReviewPipeline（审查流程编排, 首轮 + 追问轮）。

审查主流程（guard → 工作区 → 引擎 → 报告 → 消息 → SSE）实现在 service.execute_turn；
本类提供流程的阶段视图与入口（范式"② 流程"的落点），并广播 pipeline/phase 事件。
"""
from __future__ import annotations


class ReviewPipeline:
    """审查流程：首轮（understand→review→report）+ 追问轮（revise）。"""

    PHASES = ("understand", "review", "report")

    def __init__(self, ctx):
        self.ctx = ctx

    def _svc(self):
        return self.ctx.get("review")

    def _phase(self, session_id: str, name: str) -> None:
        # 事件已在 ReviewPlugin 登记（pipeline/phase）——契约内 emit, 大声失败
        self.ctx.emit("pipeline/phase", {"phase": name, "aic_session_id": session_id})

    def run(self, session_id: str, skill_text: str = "",
            knowledge_scope: list | None = None, user_message: str = "",
            conversation_history: list | None = None, turn_id: str = "") -> dict:
        """首轮审查（入口: 创建会话后投递）。"""
        self._phase(session_id, "understand")
        result = self._svc().execute_turn(
            session_id, turn_id or session_id, skill_text,
            knowledge_scope or [], user_message,
            conversation_history=conversation_history, is_followup=False)
        self._phase(session_id, "report")
        return result

    def revise(self, session_id: str, message: str, turn_id: str = "") -> dict:
        """追问轮（入口: 用户追问后投递）。"""
        return self._svc().start_turn(session_id, message, turn_id)
