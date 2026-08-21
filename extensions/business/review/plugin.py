"""review/plugin.py — 审查业务插件入口（三步法 ③ 声明）。

业务即插件: 审查 = review 插件, 挂到平台即构成审查应用。
inject: 平台能力（存储/队列/SSE/缓存/沙箱/引擎/会话）
provides: tasks(任务) / review(核心服务) / reviewPipeline(流程) / knowledge(知识) / tools(定制工具)
"""
from __future__ import annotations

from aic.kernel import Context, Plugin, ServiceNotFound

import extensions.business.review.tools  # noqa: F401  — 触发 hermes 工具注册


class ReviewPlugin(Plugin):
    """审查插件：任务 + 核心服务 + 流程 + 知识 + 定制工具。"""

    inject = ["config", "storage", "jobs", "stream", "cache", "sandbox", "agentLoop", "extract", "db", "tasks"]
    provides = ["review", "reviewPipeline", "knowledge", "tools"]

    def apply(self, ctx: Context):
        from extensions.business.review.data import Base as ReviewBase
        from extensions.business.review.security import install_patches
        from extensions.business.review.knowledge import ReviewKnowledgeProvider
        from extensions.business.review.pipeline import ReviewPipeline
        from extensions.business.review.service import ReviewService
        from extensions.business.review.task import ReviewTask
        from extensions.business.review.tools.save_review_report import SaveReviewReportTool

        ctx.get("db").create_all(ReviewBase)   # 审查表结构（引擎平台提供）

        # hermes 引擎补丁（可逆: 进效果桶, unmount 自动还原）
        for restore in install_patches():
            ctx.effect(restore)

        # 聚合键范式: 任务登记进平台注册表（effect 记账, unmount 撤销）
        ctx.effect(ctx.get("tasks").register(ReviewTask()))
        ctx.register("review", ReviewService(ctx))
        ctx.register("reviewPipeline", ReviewPipeline(ctx))
        ctx.register("knowledge", ReviewKnowledgeProvider())
        ctx.register("tools", {
            "save_review_report": SaveReviewReportTool(),
        })

        # 事件契约（0.2.1 事件注册表）: 审查阶段事件声明 + SSE 桥接
        # （pipeline.py 广播 pipeline/phase; StreamPlugin 通道化, 不认识业务事件）
        ctx.register_event("pipeline/phase", {"session_id", "phase"})
        try:
            ctx.get("stream").bridge("pipeline/phase")
        except ServiceNotFound:
            pass
