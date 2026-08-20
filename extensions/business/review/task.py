"""review/task.py — ReviewTask（AgentTask 协议）。

审查的完整系统提示词（Skill+工具规则+安全）由 service._build_system_prompt 动态拼装
（依赖 skill_text/knowledge_scope/is_followup），本类提供协议形状与基础部分。
"""
from __future__ import annotations

from aic.kernel.protocols import Phase

from extensions.business.review.security import PromptGuard, ToolPolicy


class ReviewTask:
    """审查任务：技能 SOP 审查 + 规范核查 + 报告生成。"""

    id = "review"

    def build_system_prompt(self, ctx) -> str:
        """基础系统提示词（安全规则部分; 完整提示词由 service 拼装）。"""
        return PromptGuard.build_security_prompt()

    def toolsets(self, phase: Phase) -> list[str]:
        """主代理工具集（首轮含 delegation; 追问保留）。"""
        return list(ToolPolicy.MAIN_AGENT_TOOLSETS)

    def knowledge_scope(self, meta: dict) -> list[str]:
        from extensions.business.review.knowledge import filter_knowledge
        return filter_knowledge(meta.get("project_type", "other"), meta)

    def on_result(self, session, result):
        from extensions.business.review.report import _extract_report
        return _extract_report(result)
