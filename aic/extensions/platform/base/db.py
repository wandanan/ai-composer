"""platform/base/db.py — 数据库基础设施插件（provides=["db"]）。

ctx.db: SQLAlchemy 引擎 + 会话工厂 + 建表。
- sqlite 默认（WAL + busy_timeout, 本地可跑）
- MySQL 用 URL 切换（KIT_DATABASE_URL）
业务插件的表结构（自己的 Base）通过 ctx.db.create_all(base) 建表。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from aic.kernel import Context, Plugin


def database_url() -> str:
    return os.environ.get("KIT_DATABASE_URL", "sqlite:///aic.db")


class DbService:
    """DB 服务：engine + 会话工厂 + 建表。"""

    def __init__(self, url: str | None = None):
        url = url or database_url()
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        self._engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            def _set_pragma(dbapi_conn, _rec):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()
            event.listen(self._engine, "connect", _set_pragma)
        self._factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    @property
    def engine(self):
        return self._engine

    def session(self) -> Session:
        return self._factory()

    def create_all(self, base) -> None:
        """按业务插件的 Base 建表（表结构归业务, 引擎归平台）。"""
        base.metadata.create_all(self._engine)


class DbPlugin(Plugin):
    """数据库插件：提供 ctx.db。构造注入 URL（默认环境变量 / 本地 sqlite）。"""

    PUBLIC = True   # 公共插件: 有独立生命周期, 不随任何应用卸载删除
    provides = ["db"]

    def __init__(self, url: str | None = None):
        self._url = url

    def apply(self, ctx: Context):
        ctx.register("db", DbService(self._url))
