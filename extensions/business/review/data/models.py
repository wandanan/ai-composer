"""review/models.py — 审查 DB 模型（SQLAlchemy 2.0）。

从审查应用 app.models.review（外部包, 本仓库缺失）按字段用法反推重建。
四表: review_sessions / review_messages / review_files / t_app_review_skill_desc。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ReviewSession(Base):
    __tablename__ = "review_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    file_ids: Mapped[str] = mapped_column(Text, default="[]")          # JSON list
    project_type: Mapped[str] = mapped_column(String(32), default="other")
    project_scale: Mapped[str] = mapped_column(String(255), default="")
    project_name: Mapped[str] = mapped_column(String(255), default="")
    skill_id: Mapped[str] = mapped_column(String(64), default="")
    knowledge_scope: Mapped[str] = mapped_column(Text, default="[]")   # JSON list
    batch_id: Mapped[str] = mapped_column(String(64), default="")
    report_path: Mapped[str] = mapped_column(String(255), default="")
    report_version: Mapped[int] = mapped_column(Integer, default=0)
    report_versions: Mapped[str] = mapped_column(Text, default="[]")   # JSON list
    token_usage: Mapped[str] = mapped_column(Text, default="{}")        # JSON dict
    last_error: Mapped[str] = mapped_column(Text, default="")
    review_progress: Mapped[str] = mapped_column(Text, default="[]")    # JSON list
    stats: Mapped[str] = mapped_column(Text, default="{}")              # JSON dict
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())

    # ── JSON helpers ──
    def get_file_ids(self) -> list:
        return json.loads(self.file_ids or "[]")

    def get_knowledge_scope(self) -> list:
        return json.loads(self.knowledge_scope or "[]")

    def get_report_versions(self) -> list:
        return json.loads(self.report_versions or "[]")

    def get_progress(self) -> list:
        return json.loads(self.review_progress or "[]")

    def get_token_usage(self) -> dict:
        return json.loads(self.token_usage or "{}")

    def get_stats(self) -> dict:
        return json.loads(self.stats or "{}")


class ReviewMessage(Base):
    __tablename__ = "review_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_id: Mapped[str] = mapped_column(String(64), default="")
    seq: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[str] = mapped_column(Text, default="")   # JSON str or ""
    tool_call_id: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReviewFile(Base):
    __tablename__ = "review_files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255), default="")
    file_type: Mapped[str] = mapped_column(String(16), default="")
    minio_path: Mapped[str] = mapped_column(String(255), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str] = mapped_column(Text, default="")


class ReviewSkill(Base):
    """SOP 技能表（t_app_review_skill_desc）。"""

    __tablename__ = "t_app_review_skill_desc"

    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    desc_content: Mapped[str] = mapped_column(Text, default="")
    resource: Mapped[str] = mapped_column(String(255), default="")   # MinIO zip 路径
    skill_type: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
