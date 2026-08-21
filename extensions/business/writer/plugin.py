"""biz/writer/plugin.py — 编写业务插件入口（M3）。

业务即插件：本包 = 施工方案编写业务，挂载到 agent-service-kit 平台即构成编写应用。
- inject ["sessions", "tasks"]: 依赖平台会话/任务注册表（boot 自动排序）
- inject_optional ["renderers", "stream", "agentLoop"]: 可选（renderers 缺席 md 兜底）
- provides: writerPipeline / knowledge / feedback / batch
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

    inject = ["sessions", "tasks"]
    # 可选依赖（有则拓扑排前, 无则降级）: renderers 缺席 md 兜底;
    # stream 缺席不桥接; agentLoop 调用时取（壳默认 FakeLoop 总在）
    inject_optional = ["renderers", "stream", "agentLoop"]
    provides = ["writerPipeline", "knowledge", "feedback", "batch"]

    def apply(self, ctx: Context):
        # 聚合键范式: 任务登记进平台注册表（effect 记账, unmount 撤销）
        ctx.effect(ctx.get("tasks").register(WriterTask()))
        ctx.register("writerPipeline", WriterPipeline(ctx))
        ctx.register("knowledge", WritingKnowledgeProvider())
        ctx.register("feedback", FeedbackService(ctx))
        ctx.register("batch", BatchRunner(ctx))
        try:
            # 渲染器登记同样 effect 记账（unmount 撤销, 零残留）
            ctx.effect(ctx.get("renderers").register(DocxRenderer()))
        except ServiceNotFound:
            pass  # 渲染注册表未挂载 → 跳过, md 兜底

        # 事件契约（0.2.1 事件注册表）: 声明流水线事件 + SSE 桥接
        # （平台 StreamPlugin 通道化——不认识业务事件, 桥接由业务声明;
        #   aic_session_id 是框架保留字段, 值 = 业务的会话标识）
        for evt, fields in (("pipeline/phase", {"aic_session_id", "phase"}),
                            ("chapter/status", {"aic_session_id", "chapter", "status"}),
                            ("pipeline/done", {"aic_session_id", "version"})):
            ctx.register_event(evt, fields)
        try:
            stream = ctx.get("stream")
        except ServiceNotFound:
            pass
        else:
            for evt in ("pipeline/phase", "chapter/status", "pipeline/done"):
                stream.bridge(evt)
