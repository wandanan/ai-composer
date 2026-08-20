"""apps/file_convert/worker.py — Celery worker 入口（空档位骨架, aic.tools.init 生成）。

无任务注册时的状态:
- celery_app 存在（任务名协议的内省目标: 本模块内 @celery_app.task 注册的任务名）
- 不注册任何业务任务; 需要异步任务时按 apps/mvp/worker.py 补 @celery_app.task

启动（需 Redis broker 可用）:
    python -m apps.file_convert.worker
"""
from __future__ import annotations

import os

from celery import Celery

_BROKER = os.environ.get("KIT_BROKER_URL", "redis://127.0.0.1:6379/1")

celery_app = Celery("file_convert", broker=_BROKER, backend=_BROKER)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    broker_transport_options={"visibility_timeout": 14400},
)


def main() -> None:
    """直接启动标准 celery worker（空档位: 无业务任务, 验证/空跑用）。"""
    import subprocess
    import sys

    concurrency = os.environ.get("KIT_WORKER_CONCURRENCY", "4")
    subprocess.run([
        sys.executable, "-m", "celery", "-A", "apps.file_convert.worker", "worker",
        "--loglevel=info", "--pool=threads", f"--concurrency={concurrency}",
        "-n", "file_convert@%h", "-Q", "default",
    ], check=False)


if __name__ == "__main__":
    main()
