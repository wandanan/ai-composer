"""mvp_app/worker.py — Celery worker 入口（真实执行路径）。

启动（需 Redis broker 可用）:
    python -m apps.mvp.worker                     # 直接启动（含 worker 子进程管理）
    或标准方式:
    celery -A apps.mvp.worker worker -Q mvp,mvp_followup --pool=threads --loglevel=info
"""
from __future__ import annotations

import os

from celery import Celery

from apps.mvp.tasks import TASK_REVISE, TASK_RUN_PIPELINE, _task_runner

_BROKER = os.environ.get("KIT_BROKER_URL", "redis://127.0.0.1:6379/1")

celery_app = Celery("mvp_writer", broker=_BROKER, backend=_BROKER)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    broker_transport_options={"visibility_timeout": 14400},
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_HERE, "config", "config.local.ini")
_RUNTIME_DIR = os.environ.get("KIT_SESSION_DIR", "")


def _config_path() -> str:
    return _CONFIG_PATH


def _runtime_dir() -> str:
    return _RUNTIME_DIR


@celery_app.task(name=TASK_RUN_PIPELINE)
def run_pipeline_task(session_id: str, project_info: str, chapters: list) -> dict:
    """执行 5 阶段流水线（worker 侧自举最小壳）。"""
    run_pipeline, _ = _task_runner(_config_path(), _runtime_dir())
    return run_pipeline(session_id, project_info, chapters)


@celery_app.task(name=TASK_REVISE)
def revise_task(session_id: str, feedback: str) -> dict:
    """评审反馈修订（worker 侧自举最小壳）。"""
    _, revise = _task_runner(_config_path(), _runtime_dir())
    return revise(session_id, feedback)


def main() -> None:
    """直接启动: 标准 celery worker（review 队列, threads 池）。"""
    import subprocess
    import sys

    concurrency = os.environ.get("KIT_WORKER_CONCURRENCY", "4")
    subprocess.run([
        sys.executable, "-m", "celery", "-A", "apps.mvp.worker", "worker",
        "--loglevel=info", "--pool=threads", f"--concurrency={concurrency}",
        "-n", "mvp@%h", "-Q", "mvp,mvp_followup",   # 应用域队列（与他应用隔离, 防跨应用偷任务）
    ], check=False)


if __name__ == "__main__":
    main()
