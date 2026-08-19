"""apps/review/main.py — 审查应用 HTTP 入口（strangler 重构: 存量 /front/* 端点范式化）。

壳纪律: 校验 → 调能力 → 格式化返回, 不写业务逻辑。
SSE 用平台 StreamPlugin（in-process + 可选 Redis, 事件缓冲回放）。
"""
from __future__ import annotations

import json
import queue
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from apps.review.shell import build_shell

SHELL = None

MAX_FILE_SIZE = 50 * 1024 * 1024   # 50MB（对齐原项目 FileService）


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SHELL
    SHELL = build_shell()
    yield


app = FastAPI(title="review", lifespan=lifespan)


class CreateConversationReq(BaseModel):
    file_ids: list[dict] = []          # [{"id": "..."}]（已上传文件的 file_id）
    project_type: str = "other"        # bridge/tunnel/road/building/other
    skill_id: str = ""
    metadata: dict = {}
    user_id: str = ""
    batch_id: str = ""


class TurnReq(BaseModel):
    message: str


# ── SSE 流生成器 ──

def _sse_stream(stream, session_id: str):
    q, snapshot = stream.subscribe(session_id)

    def _fmt(p: dict) -> str:
        return f"event: {p['event']}\ndata: {json.dumps(p['data'], ensure_ascii=False)}\n\n"

    try:
        for p in snapshot:                       # 事件缓冲回放（晚订阅不丢）
            yield _fmt(p)
        while True:
            try:
                p = q.get(timeout=30)
            except queue.Empty:                  # 心跳保活
                yield ": keepalive\n\n"
                continue
            if p is None:
                break
            yield _fmt(p)
    finally:
        stream.unsubscribe(session_id, q)


# ── 健康检查 ──

@app.get("/health")
async def health():
    plugins = [m.plugin.__class__.__name__ for m in SHELL._mounts]
    return {"status": "healthy", "app": "review", "plugins": plugins}


# ── 文件上传 ──

@app.post("/api/v1/files/upload")
async def upload_file(files: list[UploadFile]):
    """上传待审查文件: 存平台 storage + DB ReviewFile + 同步提取文本。

    对齐原项目 FileService.upload: 白名单校验 + 50MB 上限 + 空文件拒绝。
    """
    from extensions.business.review.data import ReviewFile
    from extensions.platform.extract import ALLOWED_TYPES

    out = []
    for f in files:
        name = f.filename or ""
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if f".{suffix}" not in ALLOWED_TYPES:
            raise HTTPException(status_code=400,
                                detail=f"不支持的文件类型: .{suffix}, 仅支持 "
                                       f"{sorted(ALLOWED_TYPES)}")
        fid = uuid.uuid4().hex[:12]
        content = await f.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="上传文件不能为空")
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)")
        key = f"review:file:{fid}:{name}"
        SHELL.get("storage").put(key, content)
        text = SHELL.get("extract").extract(content, name)
        with SHELL.get("db").session() as s:
            s.add(ReviewFile(
                id=fid, original_name=name, file_type=suffix,
                minio_path=key, file_size=len(content), extracted_text=text,
            ))
        out.append({"id": fid, "original_name": name,
                    "file_type": suffix, "file_size": len(content),
                    "extracted": bool(text)})
    return {"files": out}


# ── 会话创建（SSE）──

@app.post("/api/v1/conversations")
async def create_conversation(req: CreateConversationReq):
    try:
        result = SHELL.get("review").start_session(
            req.file_ids, req.project_type, req.skill_id,
            user_id=req.user_id, metadata=req.metadata, batch_id=req.batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return StreamingResponse(
        _sse_stream(SHELL.get("stream"), result["session_id"]),
        media_type="text/event-stream")


# ── 追问（SSE）──

@app.post("/api/v1/conversations/{session_id}")
async def followup(session_id: str, req: TurnReq):
    try:
        SHELL.get("review").start_turn(session_id, req.message)
    except ValueError as e:
        msg = str(e)
        if "FirstReviewIncompleteError" in msg:
            raise HTTPException(status_code=410, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return StreamingResponse(
        _sse_stream(SHELL.get("stream"), session_id),
        media_type="text/event-stream")


# ── SSE 重连 ──

@app.get("/api/v1/conversations/{session_id}/stream")
async def stream_reconnect(session_id: str):
    return StreamingResponse(
        _sse_stream(SHELL.get("stream"), session_id),
        media_type="text/event-stream")


# ── 查询 ──

@app.get("/api/v1/conversations/{session_id}/status")
async def get_status(session_id: str):
    try:
        return SHELL.get("review").get_status(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/conversations/{session_id}/report")
async def get_report(session_id: str, version: str = ""):
    try:
        versions = [int(v) for v in version.split(",") if v] or None
        return SHELL.get("review").get_report(session_id, versions)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/conversations/{session_id}/messages")
async def get_messages(session_id: str):
    try:
        return SHELL.get("review").get_messages(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/conversations/{session_id}")
async def get_session(session_id: str):
    try:
        SHELL.get("review").cleanup_incomplete_turns(session_id)   # 对齐原项目: 查询前清理
        return SHELL.get("review").get_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/conversations/{session_id}/messages/chat")
async def get_chat(session_id: str):
    """聊天视图（每轮留最后一条 assistant）。"""
    try:
        return SHELL.get("review").get_chat_messages(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/files/{file_id}/download")
async def download_file(file_id: str):
    """下载原始文件（对齐原项目 GET /files/{id}/download）。"""
    from fastapi.responses import Response
    from extensions.business.review.data import ReviewFile

    with SHELL.get("db").session() as s:
        f = s.get(ReviewFile, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"文件不存在: {file_id}")
        try:
            data = SHELL.get("storage").get(f.minio_path)
        except Exception:
            raise HTTPException(status_code=404, detail=f"文件内容不存在: {file_id}")
        mime = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "pdf": "application/pdf"}.get(f.file_type, "application/octet-stream")
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{f.original_name}"})


@app.get("/api/v1/conversations")
async def list_conversations(limit: int = 20):
    """最近会话列表（对齐原项目 GET /conversations）。"""
    from extensions.business.review.data import ReviewSession

    with SHELL.get("db").session() as s:
        rows = (s.query(ReviewSession)
                .order_by(ReviewSession.created_at.desc())
                .limit(limit).all())
        return {"conversations": [
            {"session_id": r.id, "project_type": r.project_type,
             "project_name": r.project_name, "skill_id": r.skill_id,
             "report_version": r.report_version,
             "created_at": str(r.created_at)} for r in rows]}


@app.get("/api/v1/concurrent-batches")
async def list_batches():
    """批次列表（按 batch_id 分组, 对齐原项目 /concurrent-batches）。"""
    from extensions.business.review.data import ReviewSession

    with SHELL.get("db").session() as s:
        rows = (s.query(ReviewSession)
                .filter(ReviewSession.batch_id != "")
                .order_by(ReviewSession.batch_id).all())
        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(r.batch_id, []).append(r)
        return {"batches": [
            {"batch_id": bid, "count": len(items),
             "sessions": [{"session_id": r.id, "project_type": r.project_type,
                           "report_version": r.report_version,
                           "status": self_status(r.id)} for r in items]}
            for bid, items in groups.items()]}


def self_status(session_id: str) -> str:
    try:
        return SHELL.get("review").get_status(session_id)["task_status"]
    except Exception:
        return "unknown"


@app.get("/api/v1/skills")
async def list_skills():
    from extensions.business.review.data import ReviewSkill
    with SHELL.get("db").session() as s:
        rows = s.query(ReviewSkill).filter(ReviewSkill.status == "active").all()
        return {"skills": [{"skill_id": r.skill_id, "name": r.name,
                            "skill_type": r.skill_type} for r in rows]}
