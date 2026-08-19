"""extensions/business/review — 施工方案审查业务插件。

从存量审查应用提炼的纯业务（SOP/工具规则/知识过滤/报告提取/审查流程），
基础设施全部由平台提供（storage/jobs/stream/cache/sandbox/agentLoop）。
"""
from extensions.business.review.plugin import ReviewPlugin

__all__ = ["ReviewPlugin"]
