"""apps/file_convert/tasks.py — 任务定义（双路径: 线程内联 + Celery worker 自举）。

空档位骨架（tools.init 生成）: 同步应用可不注册任何任务, 但文件必须存在
（壳布局契约: 装配组 tasks.py/worker.py 必须齐全）。
需要异步任务时（参考 apps/mvp/tasks.py）:
  1. 定义任务名常量 TASK_X = "file_convert.x"
  2. 实现 make_inline_tasks(shell) 线程降级路径（闭包捕获 shell）
  3. worker.py 用 @celery_app.task(name=TASK_X) 注册同名任务（任务名协议: 双侧同名）
"""
from __future__ import annotations

# ── 任务名常量（send_task 按名提交, worker 侧同名注册）──
# TASK_EXAMPLE = "file_convert.example"


def make_inline_tasks(shell):
    """线程降级路径: 复用 API 进程 shell 的内联任务（空档位, 暂无实现）。"""
    raise NotImplementedError("空档位: 需要异步任务时按上方步骤 1-3 填充")
