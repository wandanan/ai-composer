"""apps/review/worker.py — Celery worker 入口（真实执行路径）。

启动（需 Redis broker 可用）:
    python -m apps.review.worker                  # 直接启动（标准 worker）
    或:
    celery -A apps.review.worker worker -Q review,followup --pool=threads
"""
from __future__ import annotations

import os

from celery import Celery

from apps.review.tasks import (
    TASK_EXECUTE_REVIEW,
    _worker_runner,
)

_BROKER = os.environ.get("KIT_BROKER_URL", "redis://127.0.0.1:6379/1")

celery_app = Celery("review", broker=_BROKER, backend=_BROKER)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    broker_transport_options={"visibility_timeout": 14400},
)


@celery_app.task(name=TASK_EXECUTE_REVIEW)
def execute_review_task(session_id: str, turn_id: str, skill_text: str,
                        knowledge_scope: list, user_message: str,
                        conversation_history: list | None, queue: str) -> dict:
    """执行审查轮（worker 侧自举最小壳）。"""
    runner = _worker_runner()
    return runner(session_id, turn_id, skill_text, knowledge_scope,
                  user_message, conversation_history, queue)


def main() -> None:
    """直接启动: 标准 celery worker（review/followup 双队列, threads 池）。"""
    import subprocess
    import sys

    concurrency = os.environ.get("KIT_WORKER_CONCURRENCY", "4")
    subprocess.run([
        sys.executable, "-m", "celery", "-A", "apps.review.worker", "worker",
        "--loglevel=info", "--pool=threads", f"--concurrency={concurrency}",
        "-n", "review@%h", "-Q", "review,followup",
    ], check=False)


if __name__ == "__main__":
    main()
