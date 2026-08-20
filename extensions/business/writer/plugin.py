"""biz/writer/plugin.py — 编写业务插件入口（M3）。

业务即插件：本包 = 施工方案编写业务，挂载到 agent-service-kit 平台即构成编写应用。
- inject ["sessions", "renderers"]: 依赖平台会话/渲染服务（boot 自动排序）
- provides: tasks / writerPipeline / knowledge
- 注册 docx 渲染器进平台渲染注册表（renderers 未挂载时跳过, md 兜底）
"""
from __future__ import annotations

from aic.kernel import Context, Plugin, ServiceNotFound

from extensions.business.writer.batch import BatchRunner
from extensions.business.writer.feedback import FeedbackService
from extensions.business.writer.knowledge import WritingKnowledgeProvider
from extensions.business.writer.pipeline import WriterPipeline
from extensions.business.writer.render import DocxRenderer
from extensions.business.writer.task import WriterTask


class WriterPlugin(Plugin):
    """编写插件：任务 + 流水线 + 知识提供者 + 渲染器 + 反馈闭环 + 批量。"""

    inject = ["sessions", "renderers"]
    provides = ["tasks", "writerPipeline", "knowledge", "feedback", "batch"]

    def apply(self, ctx: Context):
        ctx.register("tasks", {WriterTask.id: WriterTask()})
        ctx.register("writerPipeline", WriterPipeline(ctx))
        ctx.register("knowledge", WritingKnowledgeProvider())
        ctx.register("feedback", FeedbackService(ctx))
        ctx.register("batch", BatchRunner(ctx))
        try:
            ctx.get("renderers").register(DocxRenderer())
        except ServiceNotFound:
            pass  # 渲染注册表未挂载 → 跳过, md 兜底

        # 事件契约（0.2.1 事件注册表）: 声明流水线事件 + SSE 桥接
        # （平台 StreamPlugin 通道化——不认识业务事件, 桥接由业务声明）
        for evt, fields in (("pipeline/phase", {"session_id", "phase"}),
                            ("chapter/status", {"session_id", "chapter", "status"}),
                            ("pipeline/done", {"session_id", "version"})):
            ctx.register_event(evt, fields)
        try:
            stream = ctx.get("stream")
        except ServiceNotFound:
            pass
        else:
            for evt in ("pipeline/phase", "chapter/status", "pipeline/done"):
                stream.bridge(evt)
