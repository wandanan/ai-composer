"""review/report.py — 审查报告提取/标题解析/提交守卫（从审查应用移植）。

- _extract_title: 从 Markdown 首行提取标题
- _extract_report: 从 agent 结果提取 save_review_report 工具调用正文（跳过历史轮）
- ReportGuard: 报告提交参数校验 + 文件名净化
"""
from __future__ import annotations

import json
import logging

from aic.extensions.platform.security.sanitize import sanitize_filename

logger = logging.getLogger(__name__)


def _extract_title(md: str) -> str:
    """从 Markdown 正文首行提取标题（# 开头的行）。"""
    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped and not stripped.startswith("<!--"):
            return stripped[:100]
    return ""


def _extract_report(result: dict, conversation_history: list | None = None) -> str:
    """从 agent 返回结果中提取审查报告正文（仅 save_review_report 工具调用的 content）。

    只扫描本轮新消息，跳过 conversation_history + 当前 user message，
    避免追问轮中误提取历史轮的 save_review_report 调用。
    """
    messages = result.get("messages", []) or []
    skip = len(conversation_history or []) + 1

    for msg in reversed(messages[skip:]):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = (tc.get("function") or {})
                name = fn.get("name", "")
                try:
                    args_str = fn.get("arguments", "") or ""
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"工具调用参数 JSON 解析失败: {e} | name={name}")
                    continue
                if name == "save_review_report":
                    content = args.get("content", "")
                    if content:
                        logger.info(f"从 save_review_report 工具提取报告: {len(content)} 字符")
                        return content
    return ""


class ReportGuard:
    """报告提交安全守卫。"""

    @staticmethod
    def validate_report(*, is_final_report: bool, content: str,
                        session_id: str, title: str = "") -> tuple[bool, str]:
        if not session_id:
            return False, "session_id 缺失，工具上下文未正确设置"
        if not content or not content.strip():
            return False, "报告内容不能为空"
        if not is_final_report:
            preview = content[:200] if content else ""
            return False, (
                "is_final_report 必须为 true 才能保存。"
                "请核查以下内容是否为本轮审查的最终报告，确认后设置 is_final_report=true 重新调用："
                f"标题={title}，正文长度={len(content)} 字符，"
                f"正文前 200 字符={preview}"
            )
        return True, ""

    @staticmethod
    def sanitize_report_filename(filename: str) -> str:
        return sanitize_filename(filename)
