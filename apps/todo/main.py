"""todo — 待办管理应用（非 AI 应用示例, 纯数据服务型）。

应用 = 平台 + 插件组合: 待办业务由 extensions/business/todo 提供,
数据经平台 storage 协议持久化（无文件产物）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from apps.todo.shell import build_shell

SHELL = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SHELL
    SHELL = build_shell()
    yield


app = FastAPI(title="todo", lifespan=lifespan)


@app.get("/health")
async def health():
    from aic.kernel import ServiceNotFound
    plugins = [m.plugin.__class__.__name__ for m in SHELL._mounts]
    jobs_health = "?"
    try:
        jobs_health = SHELL.get("jobs").health()
    except ServiceNotFound:
        pass
    return {"status": "healthy", "app": "todo", "plugins": plugins,
            "jobs_health": jobs_health}


class TodoReq(BaseModel):
    title: str


@app.post("/api/v1/lists")
async def create_list():
    """创建待办列表（一次列表 = 一个会话上下文）。"""
    session = SHELL.get("sessions").create_session({"list": "todos"})
    return {"session_id": session.session_id}


@app.get("/api/v1/lists/{session_id}/todos")
async def list_todos(session_id: str):
    return {"todos": SHELL.get("todos").list(session_id)}


@app.post("/api/v1/lists/{session_id}/todos")
async def add_todo(session_id: str, req: TodoReq):
    return SHELL.get("todos").add(session_id, req.title)


@app.post("/api/v1/lists/{session_id}/todos/{todo_id}/complete")
async def complete_todo(session_id: str, todo_id: int):
    try:
        return SHELL.get("todos").complete(session_id, todo_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

