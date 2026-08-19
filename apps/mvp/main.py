"""mvp_app/main.py — 编写应用 MVP：FastAPI 可运行 + 全插件装配。

运行:
    PYTHONIOENCODING=utf-8 python -m uvicorn mvp_app.main:app --port 8007
    （KIT_ENGINE=hermes 用真实引擎; 默认 fake 免 API 成本）
    任务: Redis 可用 → Celery worker; 不可用 → 线程池降级（自动）
"""
from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from kernel import Context
from extensions.platform.session.artifacts import list_artifacts
from apps.mvp.shell import build_shell
from apps.mvp.tasks import TASK_REVISE, TASK_RUN_PIPELINE, make_inline_tasks

SHELL: Context | None = None
_MOUNTS = []


class CreateConversationReq(BaseModel):
    project_info: str
    chapters: list[str] = ["编制依据", "工程概况", "施工部署"]


class ReviseReq(BaseModel):
    feedback: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SHELL
    shell, mounts = build_shell()
    _MOUNTS.extend(mounts)
    SHELL = shell
    print(f"[mvp] 装配完成: {[m.plugin.__class__.__name__ for m in mounts]}")
    yield
    for m in reversed(_MOUNTS):
        SHELL.unmount(m)


app = FastAPI(title="const-plan-writer-mvp", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    shell = SHELL
    return {
        "status": "healthy",
        "plugins": [m.plugin.__class__.__name__ for m in _MOUNTS],
        "jobs": type(shell.get("jobs")).__name__,
        "jobs_health": shell.get("jobs").health(),
    }


@app.post("/api/v1/conversations")
async def create_conversation(req: CreateConversationReq):
    """创建编写会话（SSE）：创建 → 派发 → 全进度推送 → done, 单连接闭环。"""
    shell = SHELL
    session = shell.get("sessions").create_session({"project": req.project_info})
    svc = shell.get("stream")
    q, snapshot = svc.subscribe(session.session_id)

    async def gen():
        try:
            yield _sse("session_created", {"session_id": session.session_id,
                                           "task_status": "queued"})
            for item in snapshot:                       # 防御性回放（通常为空）
                yield _sse(item["event"], item["data"])
            # 订阅建立后再派发, 保证事件不丢
            run_pipeline, revise = make_inline_tasks(shell)
            jobs = shell.get("jobs")
            jobs.register_task(TASK_RUN_PIPELINE, run_pipeline)
            jobs.register_task(TASK_REVISE, revise)
            jobs.enqueue(TASK_RUN_PIPELINE,
                         [session.session_id, req.project_info, req.chapters],
                         queue="review")
            while True:
                try:
                    item = await asyncio.to_thread(q.get, timeout=15)
                except Exception:
                    yield _sse("heartbeat", {})        # 15s 心跳保活
                    continue
                yield _sse(item["event"], item["data"])
                if item["event"] == "pipeline/done":
                    break
        finally:
            svc.unsubscribe(session.session_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/v1/conversations/{session_id}")
async def get_conversation(session_id: str):
    shell = SHELL
    try:
        session = shell.get("sessions").attach(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail="会话不存在")
    output_files = list_artifacts(session.dir, "output")
    return {
        "session_id": session_id,
        "meta": session.meta,
        "done": bool(output_files),
        "outputs": output_files,
        "chapters": list_artifacts(session.dir, "chapters"),
        "merged": list_artifacts(session.dir, "merged"),
    }


@app.post("/api/v1/conversations/{session_id}/revise")
async def revise(session_id: str, req: ReviseReq):
    shell = SHELL
    try:
        shell.get("sessions").attach(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail="会话不存在")
    task_id = shell.get("jobs").enqueue(TASK_REVISE, [session_id, req.feedback],
                                        queue="followup")
    return {"session_id": session_id, "task_id": task_id}


# ── SSE 进度推送 ──────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _redis_to_queue(redis_url: str, session_id: str, q) -> None:
    """daemon 线程: Redis pub/sub（Celery worker 跨进程路径）→ in-process 队列。"""
    try:
        import redis as redis_sync
        r = redis_sync.Redis.from_url(redis_url, socket_connect_timeout=1,
                                      decode_responses=True)
        ps = r.pubsub()
        ps.subscribe(f"sse:{session_id}")
        for msg in ps.listen():
            if msg.get("type") == "message":
                q.put(json.loads(msg["data"]))
    except Exception:
        pass  # Redis 不可用时仅 in-process 通道


@app.get("/api/v1/conversations/{session_id}/stream")
async def stream_conversation(session_id: str):
    """SSE 进度流：session_created → pipeline/phase* → chapter/status* → pipeline/done。"""
    shell = SHELL
    try:
        shell.get("sessions").attach(session_id)
    except Exception:
        raise HTTPException(status_code=404, detail="会话不存在")

    svc = shell.get("stream")
    q, snapshot = svc.subscribe(session_id)

    async def gen():
        redis_thread = None
        try:
            yield _sse("session_created", {"session_id": session_id})
            # 回放已发生事件（订阅晚于事件时兜底）
            for item in snapshot:
                yield _sse(item["event"], item["data"])
            if any(item["event"] == "pipeline/done" for item in snapshot):
                return  # 会话已完成: 回放后断开
            if svc.redis_enabled:
                redis_thread = threading.Thread(
                    target=_redis_to_queue, args=(svc.redis_url, session_id, q),
                    daemon=True)
                redis_thread.start()
            while True:
                try:
                    item = await asyncio.to_thread(q.get, timeout=15)
                except Exception:
                    yield _sse("heartbeat", {})   # 15s 心跳保活
                    continue
                yield _sse(item["event"], item["data"])
                if item["event"] == "pipeline/done":
                    break
        finally:
            svc.unsubscribe(session_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")
