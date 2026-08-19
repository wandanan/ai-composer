"""kit/session — 会话与产物服务（平台 base bundle 的 M2 最小版）。

- SessionService (ctx.sessions): 会话创建/查询/轮次
- 产物管理 (artifacts.py): 会话工作区内的多产物落盘与版本化
多轮 turn 编排、锁、持久化在 base bundle 协议化阶段（strangler）从 ReviewService 迁移补齐。
"""
from .session_service import Session, SessionNotFound, SessionPlugin, SessionService

__all__ = ["Session", "SessionNotFound", "SessionPlugin", "SessionService"]
