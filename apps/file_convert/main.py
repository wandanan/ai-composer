"""file_convert — 文件格式转换应用（非 AI 应用示例）。

应用 = 平台 + 插件组合: 转换业务由 extensions/business/file_convert 提供。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from apps.file_convert.shell import build_shell

SHELL = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SHELL
    SHELL = build_shell()
    yield


app = FastAPI(title="file_convert", lifespan=lifespan)


@app.get("/health")
async def health():
    from aic.kernel import ServiceNotFound
    plugins = [m.plugin.__class__.__name__ for m in SHELL._mounts]
    jobs_health = "?"
    try:
        jobs_health = SHELL.get("jobs").health()
    except ServiceNotFound:
        pass
    return {"status": "healthy", "app": "file_convert", "plugins": plugins,
            "jobs_health": jobs_health}


class ConvertReq(BaseModel):
    content: str
    src_type: str = "txt"
    dst_type: str = "md"


@app.post("/api/v1/convert")
async def convert(req: ConvertReq):
    """文件转换（同步）: 创建任务上下文 → 流程执行 → 产物落盘。"""
    session = SHELL.get("sessions").create_session({"job": "convert"})
    result = SHELL.get("convertPipeline").run(
        session, req.content, req.src_type, req.dst_type)
    return {"session_id": session.aic_session_id, **result}

