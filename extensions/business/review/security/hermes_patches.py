"""review/hermes_patches.py — hermes 引擎审查补丁（可逆, 效果桶模式）。

从审查应用 app/core/hack_hermes/ 移植（re_resolve_path → 平台 SandboxPlugin,
check_toolset → 平台 HermesLoop）:
  1. delegate_task 子代理工具集白名单（剥离越权/未知 toolset, 安全默认值）
  2. run_conversation 主代理未调 save_review_report 时续跑（强制出报告）

install_patches() 返回还原函数列表, 由插件 apply 进效果桶 → unmount 自动还原。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

from extensions.business.review.security.prompt import ToolPolicy


# ── 补丁 1: 子代理工具集白名单 ──────────────────────────

_ALLOWED = set(ToolPolicy.SUB_AGENT_TOOLSETS)
_FORBIDDEN = frozenset(ToolPolicy.FORBIDDEN_SUB_AGENT_TOOLSETS)


def _sanitize_toolsets(toolsets, label: str = ""):
    if not toolsets:
        return toolsets, False
    cleaned = [t for t in toolsets if t not in _FORBIDDEN and t in _ALLOWED]
    had = len(cleaned) != len(toolsets)
    if had:
        forbidden = [t for t in toolsets if t in _FORBIDDEN]
        unknown = [t for t in toolsets if t not in _FORBIDDEN and t not in _ALLOWED]
        logger.warning("[review] delegate_task%s 越权工具集: 剥离=%s 未知=%s → %s",
                       f" ({label})" if label else "",
                       forbidden, unknown, cleaned)
    if not cleaned:
        cleaned = list(_ALLOWED)
    return cleaned, had


def _sanitize_tasks(tasks):
    if not tasks:
        return tasks, False
    if isinstance(tasks, str):
        try:
            parsed = json.loads(tasks)
        except json.JSONDecodeError:
            return tasks, False
        if not isinstance(parsed, list):
            return tasks, False
        any_had = False
        for i, task in enumerate(parsed):
            if isinstance(task, dict) and "toolsets" in task:
                cleaned, had = _sanitize_toolsets(task.get("toolsets"), f"task[{i}]")
                task["toolsets"] = cleaned
                any_had = any_had or had
        return (json.dumps(parsed, ensure_ascii=False) if any_had else tasks), any_had
    if isinstance(tasks, list):
        any_had = False
        for i, task in enumerate(tasks):
            if isinstance(task, dict) and "toolsets" in task:
                cleaned, had = _sanitize_toolsets(task.get("toolsets"), f"task[{i}]")
                task["toolsets"] = cleaned
                any_had = any_had or had
        return tasks, any_had
    return tasks, False


def _patch_delegate_task() -> list[Callable[[], None]]:
    """包装 delegate_task: 剥离子代理越权/未知工具集, 防绕过 SUB_AGENT 白名单。"""
    try:
        import tools.delegate_tool as dt
    except ImportError:
        return []

    original = dt.delegate_task

    def _wrapped(goal=None, context=None, toolsets=None, tasks=None,
                 max_iterations=None, acp_command=None, acp_args=None,
                 role=None, parent_agent=None, **kw):
        toolsets, _ = _sanitize_toolsets(toolsets, "top-level")
        tasks, _ = _sanitize_tasks(tasks)
        return original(goal=goal, context=context, toolsets=toolsets,
                        tasks=tasks, max_iterations=max_iterations,
                        acp_command=acp_command, acp_args=acp_args,
                        role=role, parent_agent=parent_agent, **kw)

    if getattr(dt.delegate_task, "__review_patched__", False):
        return []
    _wrapped.__review_patched__ = True
    dt.delegate_task = _wrapped
    logger.info("[review] hermes patch: delegate_task → 子代理工具集白名单")
    return [lambda: setattr(dt, "delegate_task", original)]


# ── 补丁 2: 主代理未出报告续跑 ──────────────────────────

_MAX_NUDGES = 2
_NUDGE_MESSAGE = (
    "你尚未提交审查报告。请基于已读取的全部内容，直接调用 save_review_report 工具"
    "提交最终报告（is_final_report=true，title=报告标题，content=完整报告正文）。"
    "不要再读取文件或进行其他工具调用。"
)


def _has_save_review_report_call(messages) -> bool:
    for msg in messages or []:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                if fn.get("name") == "save_review_report":
                    return True
    return False


def _is_main_review_agent(agent) -> bool:
    toolsets = getattr(agent, "enabled_toolsets", None) or []
    return "save_review_report" in toolsets


def _patch_ensure_final_report() -> list[Callable[[], None]]:
    """包装 conversation_loop.run_conversation: 主代理未调 save_review_report 则续跑。"""
    try:
        import agent.conversation_loop as cl
    except ImportError:
        return []

    original = cl.run_conversation

    def _wrapped(agent, user_message, system_message=None,
                 conversation_history=None, task_id=None,
                 stream_callback=None, persist_user_message=None, **kw):
        result = original(agent, user_message, system_message, conversation_history,
                          task_id, stream_callback, persist_user_message, **kw)
        if not _is_main_review_agent(agent):
            return result
        if _has_save_review_report_call(result.get("messages", [])):
            return result

        logger.warning("[review] 主代理未调 save_review_report, 注入续跑 (max=%d)", _MAX_NUDGES)
        history = list(conversation_history or []) + list(result.get("messages", []) or [])
        for i in range(_MAX_NUDGES):
            result = original(agent, _NUDGE_MESSAGE, system_message, history,
                              task_id, stream_callback, persist_user_message, **kw)
            if _has_save_review_report_call(result.get("messages", [])):
                logger.info("[review] 续跑 %d/%d 后已调用 save_review_report", i + 1, _MAX_NUDGES)
                return result
            history += list(result.get("messages", []) or [])
        return result

    if getattr(cl.run_conversation, "__review_patched__", False):
        return []
    _wrapped.__review_patched__ = True
    cl.run_conversation = _wrapped
    logger.info("[review] hermes patch: run_conversation → 主代理未出报告续跑")
    return [lambda: setattr(cl, "run_conversation", original)]


# ── 统一安装 ─────────────────────────────────────────────

def install_patches() -> list[Callable[[], None]]:
    """安装审查专属补丁, 返回还原函数列表（进插件效果桶, unmount 自动还原）。"""
    restore: list[Callable[[], None]] = []
    restore += _patch_delegate_task()
    restore += _patch_ensure_final_report()
    return restore
