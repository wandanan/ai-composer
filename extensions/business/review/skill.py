"""review/skill.py — 审查 Skill（SOP）加载。

审查应用的 SOP 存于 DB 表 t_app_review_skill_desc；
本插件通过可注入的 provider 读取（DB 实现见 models/db_provider.py）。
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# 默认 provider: 从文件读取（knowledge-base/skills/{skill_id}/SKILL.md）
# strangler 阶段可替换为 DB provider（t_app_review_skill_desc）
def _file_provider(skill_id: str) -> str:
    import os
    from extensions.business.review.knowledge import get_knowledge_base_dir
    for cand in (
        os.path.join(get_knowledge_base_dir(), "skills", skill_id, "SKILL.md"),
        os.path.join(get_knowledge_base_dir(), "skills", f"{skill_id}.md"),
    ):
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8") as f:
                content = f.read()
            if content:
                logger.info(f"加载 Skill: {skill_id}, 长度: {len(content)} 字符")
                return content
    raise ValueError(f"Skill 不存在: {skill_id}")


def load_skill(skill_id: str, provider: Callable[[str], str] | None = None) -> str:
    """加载指定 skill_id 的 SOP 文本。provider 可注入（默认文件实现）。"""
    if provider is None:
        provider = _file_provider
    return provider(skill_id)
