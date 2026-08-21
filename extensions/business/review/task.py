"""review/task.py — ReviewTask（AgentTask 协议）。

审查的完整系统提示词（Skill+工具规则+安全）由 service._build_system_prompt 动态拼装
（依赖 skill_text/knowledge_scope/is_followup），本类提供协议形状与基础部分。
"""
from __future__ import annotations

from aic.extensions.platform.agent import Phase

from extensions.business.review.security import PromptGuard, ToolPolicy

# 异步任务名（插件能力名单一来源）: 壳 tasks.py 内联注册与 worker.py
# @celery_app.task 双侧同名（任务名协议）; 插件 service 按此名 enqueue——
# 名字归插件（能力声明）, 壳只做接线（方向: 壳 → 插件, 不倒置）。
TASK_EXECUTE_REVIEW = "review.execute_review"


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
