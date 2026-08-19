"""kit/session/session_service.py — 会话服务（ctx.sessions，M2 最小版）。

范围：会话创建/查询 + 会话目录 + 元数据 + 轮次计数。
多轮 turn 编排、分布式锁、DB 持久化在 base bundle 协议化阶段
（strangler）从 ReviewService 迁移补齐（M4）。
"""
from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass, field

from kernel import Context, Plugin


class SessionNotFound(KeyError):
    """会话不存在。"""


@dataclass
class Session:
    """一个业务会话 = 一个完整工作区 + 元数据 + 轮次。"""

    session_id: str
    dir: str          # 会话工作区目录（产物落盘于此）
    meta: dict        # 业务元数据（方案类型/项目名等，JSON 化后由业务解释）
    turn: int = 0     # 轮次计数（首轮 + 追问轮）


class SessionService:
    """会话服务：创建/查询会话。M2 用内存注册表 + 文件系统工作区。"""

    def __init__(self, runtime_dir: str | None = None):
        self._runtime_dir = runtime_dir or os.path.join(
            tempfile.gettempdir(), "kit_sessions")
        self._sessions: dict[str, Session] = {}

    @property
    def runtime_dir(self) -> str:
        return self._runtime_dir

    def create_session(self, meta: dict | None = None) -> Session:
        sid = uuid.uuid4().hex[:12]
        sdir = os.path.join(self._runtime_dir, sid)
        os.makedirs(sdir, exist_ok=True)
        session = Session(session_id=sid, dir=sdir, meta=meta or {})
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        return self._sessions[session_id]

    def attach(self, session_id: str, meta: dict | None = None) -> Session:
        """重建会话（跨进程：worker/线程任务端按 session_id 恢复工作区）。

        runtime_dir 默认一致（tempdir/kit_sessions），API 进程创建、执行端 attach。
        """
        if session_id in self._sessions:
            return self._sessions[session_id]
        sdir = os.path.join(self._runtime_dir, session_id)
        if not os.path.isdir(sdir):
            raise SessionNotFound(session_id)
        session = Session(session_id=session_id, dir=sdir, meta=meta or {})
        self._sessions[session_id] = session
        return session

    def start_turn(self, session: Session) -> int:
        session.turn += 1
        return session.turn


class SessionPlugin(Plugin):
    """会话服务插件：提供 ctx.sessions。

    runtime_dir: 会话工作区根目录（默认系统临时目录 kit_sessions）。
    多进程/多机部署传共享目录——跨进程 attach 靠目录存在恢复（见 06 部署前检查清单）。
    """

    provides = ["sessions"]

    def __init__(self, runtime_dir: str | None = None):
        self._runtime_dir = runtime_dir

    def apply(self, ctx: Context):
        ctx.register("sessions", SessionService(self._runtime_dir))
