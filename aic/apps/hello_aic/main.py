"""hello_aic — hello_aic 应用壳（aic.tools.init 生成）。

应用 = 平台 + 插件组合。改 profile.py 挂载业务插件。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from aic.apps.hello_aic.shell import build_shell

SHELL = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SHELL
    SHELL = build_shell()
    yield


app = FastAPI(title="hello_aic", lifespan=lifespan)


@app.get("/health")
async def health():
    from aic.kernel import ServiceNotFound
    plugins = [m.plugin.__class__.__name__ for m in SHELL._mounts]
    jobs_health = "?"
    try:
        jobs_health = SHELL.get("jobs").health()
    except ServiceNotFound:
        pass
    return {"status": "healthy", "app": "hello_aic", "plugins": plugins,
            "jobs_health": jobs_health}
