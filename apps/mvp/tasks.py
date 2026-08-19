"""mvp_app/tasks.py — 任务定义（双路径: 线程池内联 + Celery worker 自举）。

同一任务名 "writer.run_pipeline" / "writer.revise":
- 线程降级路径: API 进程内闭包（共享 shell）
- Celery 路径:   worker 进程自举最小壳（独立装配, send_task 按名命中）
"""
from __future__ import annotations

import json
import os

# ── 任务名常量（send_task 按名提交, worker 侧同名注册）──
TASK_RUN_PIPELINE = "writer.run_pipeline"
TASK_REVISE = "writer.revise"


def _task_runner(config_path: str, runtime_dir: str):
    """返回 (run_pipeline, revise) 两个自举任务函数（Celery worker 路径）。

    worker 进程没有 API 侧 shell, 自行装配（与 API 进程同一组合, 见 shell.build_shell）。
    """
    from apps.mvp.shell import build_shell

    def _shell():
        shell, _ = build_shell(config_path)
        return shell

    def run_pipeline(session_id: str, project_info: str, chapters: list) -> dict:
        ctx = _shell()
        session = ctx.get("sessions").attach(session_id)
        result = ctx.get("writerPipeline").run(session, project_info, chapters)
        ctx.get("telemetry").trace("pipeline/done", **{k: v for k, v in result.items()
                                                       if k != "outputs"})
        ctx.get("storage").put(f"{session_id}/pipeline_result.json",
                               json.dumps(result, ensure_ascii=False).encode())
        return result

    def revise(session_id: str, feedback: str) -> dict:
        ctx = _shell()
        session = ctx.get("sessions").attach(session_id)
        return ctx.get("feedback").revise_by_feedback(session, feedback)

    return run_pipeline, revise


def make_inline_tasks(shell):
    """线程降级路径: 复用 API 进程 shell 的内联任务（闭包捕获 shell）。"""
    from extensions.platform.session.artifacts import list_artifacts

    def run_pipeline(session_id: str, project_info: str, chapters: list) -> dict:
        session = shell.get("sessions").attach(session_id)
        result = shell.get("writerPipeline").run(session, project_info, chapters)
        shell.get("telemetry").trace(
            "pipeline/done", version=result["version"], chapters=result["chapters"])
        shell.get("storage").put(f"{session_id}/pipeline_result.json",
                                 json.dumps(result, ensure_ascii=False).encode())
        return result

    def revise(session_id: str, feedback: str) -> dict:
        session = shell.get("sessions").attach(session_id)
        return shell.get("feedback").revise_by_feedback(session, feedback)

    return run_pipeline, revise
