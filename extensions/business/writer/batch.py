"""biz/writer/batch.py — 批量编写（M4）。

多方案并行编写：每方案一个独立会话（工作区/产物隔离），
线程池并发执行完整流水线，逐个收集结果，单个失败不阻断其余。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from aic.kernel import Context


class BatchRunner:
    """批量编写器：并行运行多个方案的完整流水线。"""

    def __init__(self, ctx: Context, concurrency: int = 4):
        self.ctx = ctx
        self.concurrency = concurrency

    def run(self, projects: list[dict]) -> dict:
        """projects: [{"name": 方案名, "chapters": [章节名, ...]}, ...]

        返回 {session_id: pipeline 结果或 error}。
        """
        sessions = self.ctx.get("sessions")
        pipeline = self.ctx.get("writerPipeline")
        results: dict = {}
        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            futures = {}
            for p in projects:
                session = sessions.create_session({"project": p["name"]})
                futures[ex.submit(pipeline.run, session, p["name"], p["chapters"])] = session
            for fut in as_completed(futures):
                session = futures[fut]
                try:
                    results[session.session_id] = fut.result()
                except Exception as exc:  # 单个失败不阻断其余
                    results[session.session_id] = {"error": str(exc)}
        return results
