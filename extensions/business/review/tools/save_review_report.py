"""review/tools/save_review_report.py — 审查报告保存工具（业务定制）。

由 LLM 主动调用保存最终报告。handler 只做本地落盘（reports/）；
MinIO 上传 + 版本化由 pipeline 执行后在产物通道处理（避免依赖 DB 在 worker 线程间传递）。
"""
from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime
from typing import Callable

from extensions.business.review.report import ReportGuard

logger = logging.getLogger(__name__)

# 审查上下文：pipeline 执行前注入，tool handler 读取（沿用审查应用的 ContextVar 方案）
_review_ctx: ContextVar[dict] = ContextVar("review_ctx", default={})


def set_review_context(*, session_id: str, work_dir: str, session=None) -> None:
    _review_ctx.set({
        "session_id": session_id,
        "work_dir": work_dir,
        "session": session,
    })


def get_review_context() -> dict:
    return _review_ctx.get()


class SaveReviewReportTool:
    """save_review_report 工具：校验 + 本地落盘 reports/。"""

    name = "save_review_report"
    toolset = "save_review_report"
    schema = {
        "name": "save_review_report",
        "description": (
            "保存最终审查报告。仅限审查全部完成后调用，禁止用于中间草稿。"
            "调用前必须确认 content 是完整的最终报告。"
            "is_final_report 必须设为 true 才会执行保存。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "is_final_report": {
                    "type": "boolean",
                    "description": "必须为 true。确认当前内容是本轮审查的最终正式报告。设 false 或不传则保存失败并收到提醒。"
                },
                "title": {
                    "type": "string",
                    "description": "审查报告标题，如「编制依据联网核查报告」"
                },
                "content": {
                    "type": "string",
                    "description": "完整的审查报告正文（Markdown 或 HTML），必须包含所有核查结果和建议"
                },
            },
            "required": ["is_final_report", "title", "content"],
        },
    }

    def handle(self, args: dict, **kw) -> str:
        ctx = _review_ctx.get()
        session_id = ctx.get("session_id", "")
        work_dir = ctx.get("work_dir", "")

        title = (args.get("title") or "").strip()
        content = (args.get("content") or "").strip()
        is_final = args.get("is_final_report", False)

        passed, error_msg = ReportGuard.validate_report(
            is_final_report=is_final,
            content=content,
            session_id=session_id,
            title=title,
        )
        if not passed:
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)

        output_dir = os.path.join(work_dir, "reports") if work_dir else ""
        local_path = ""
        try:
            os.makedirs(output_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = "编制依据联网核查报告" if "编制依据" in title else title
            filename = ReportGuard.sanitize_report_filename(filename)
            local_path = os.path.join(output_dir, f"report_{filename}_{ts}.md")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"save_review_report: 本地保存成功 {local_path} ({len(content)} 字符)")
        except Exception as e:
            logger.warning(f"save_review_report: 本地保存失败 {e}")

        return json.dumps({
            "success": True,
            "title": title,
            "size": len(content),
            "local_path": local_path,
        }, ensure_ascii=False)


def register_review_report_tool(tool: "SaveReviewReportTool") -> "Callable[[], None] | None":
    """把给定实例注册进 hermes 工具系统, 返回注销 disposer（非 hermes 环境返回 None）。

    生命周期归 ReviewPlugin apply（mount 注册 / unmount 注销）——不在模块级
    自注册: import 无副作用（旧实现在 import 时写 hermes 全局注册表,
    绕过内核效果桶, unmount 残留）。
    """
    try:
        from tools.registry import registry
    except ImportError:
        logger.debug("[review] tools.registry 未安装（非 hermes 环境），跳过 save_review_report 注册")
        return None
    registry.register(
        name=tool.name,
        toolset=tool.toolset,
        schema=tool.schema,
        handler=tool.handle,
        check_fn=None,
        description="保存审查报告并自动上传到云端",
        emoji="📋",
    )
    return lambda: registry.deregister(tool.name)
