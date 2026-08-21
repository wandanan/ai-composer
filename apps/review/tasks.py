"""apps/review/tasks.py — 审查任务定义（双路径: 线程内联 + Celery worker 自举）。

同一任务名 "review.execute_review":
- 线程降级路径: API 进程闭包（共享 shell, 经 jobs.register_task 注册）
- Celery 路径:   worker 进程自举最小壳（send_task 按名命中同名任务）
"""
from __future__ import annotations

# 任务名单一来源在插件侧（能力归插件, 壳只做双侧同名接线）
from extensions.business.review.task import TASK_EXECUTE_REVIEW  # noqa: F401

QUEUE_REVIEW = "review"
QUEUE_FOLLOWUP = "followup"


def make_execute_review(shell):
    """返回 execute_review 内联任务（闭包捕获 shell）。"""
    def execute_review(session_id: str, turn_id: str, skill_text: str,
                       knowledge_scope: list, user_message: str,
                       conversation_history: list | None, queue: str) -> dict:
        return shell.get("review").execute_turn(
            session_id, turn_id, skill_text, knowledge_scope, user_message,
            conversation_history=conversation_history,
            is_followup=(queue == QUEUE_FOLLOWUP))
    return execute_review


def _worker_runner():
    """Celery worker 路径: 自举最小壳后执行（worker 进程无 API shell）。"""
    from apps.review.shell import build_shell

    def execute_review(session_id: str, turn_id: str, skill_text: str,
                       knowledge_scope: list, user_message: str,
                       conversation_history: list | None, queue: str) -> dict:
        shell = build_shell()
        return shell.get("review").execute_turn(
            session_id, turn_id, skill_text, knowledge_scope, user_message,
            conversation_history=conversation_history,
            is_followup=(queue == QUEUE_FOLLOWUP))
    return execute_review
