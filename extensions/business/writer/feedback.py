"""biz/writer/feedback.py — 评审反馈闭环（M4）。

外部评审意见 → 定位章节 → 修订（重写/重合并/重渲染, 版本递增）。
定位策略（M4 启发式）：按章节名关键词匹配 chapters/*.md。
"""
from __future__ import annotations

from kernel import Context
from extensions.platform.session.artifacts import list_artifacts


class FeedbackService:
    """把评审反馈定位到章节文件并触发修订。"""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def locate(self, session, feedback: str) -> str | None:
        """按章节名关键词定位：返回 chapters/*.md 文件名；找不到返回 None。"""
        for name in list_artifacts(session.dir, "chapters"):
            base = name[:-3]  # 去 .md
            chapter = base.split("_", 1)[-1] if "_" in base else base
            if chapter in feedback:
                return name
        return None

    def revise_by_feedback(self, session, feedback: str) -> dict:
        """反馈修订闭环：定位 → pipeline.revise（重写章节/重合并/重渲染）。"""
        chapter_file = self.locate(session, feedback)
        if chapter_file is None:
            raise ValueError(f"无法从评审反馈定位章节: {feedback[:50]}…")
        return self.ctx.get("writerPipeline").revise(session, feedback, chapter_file)
