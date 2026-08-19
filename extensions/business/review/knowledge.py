"""review/knowledge.py — 审查知识范围筛选（从审查应用 knowledge.py 移植）。

按项目类型 + 关键词筛选知识库目录，返回审查依据目录列表。
根路径来源: 环境变量 KNOWLEDGE_BASE_DIR > 构造参数 > 默认 ./knowledge-base。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def get_knowledge_base_dir() -> str:
    env_dir = os.environ.get("KNOWLEDGE_BASE_DIR")
    if env_dir:
        return env_dir
    return os.path.abspath("./knowledge-base")


def _get_knowledge_base() -> str:
    return os.path.join(get_knowledge_base_dir(), "knowledge", "standards")


DEFAULT_KNOWLEDGE_BASE = _get_knowledge_base()

PROJECT_TYPE_MAP = {
    "bridge": ["桥梁"],
    "tunnel": ["隧道"],
    "road": ["道路"],
    "building": ["建筑"],
    "other": [],
}

COMMON_DIRS = ["安全"]

# subdir → 触发关键词
KEYWORD_MAP = {
    "高处作业": ["高处作业", "高空", "临边", "洞口防护"],
    "桥梁": ["桥梁", "桥墩", "桥面", "箱梁", "挂篮", "预应力"],
    "隧道": ["隧道", "掘进", "管棚", "衬砌", "暗挖"],
    "临时用电": ["临时用电", "配电箱", "用电组织设计"],
    "脚手架": ["脚手架", "模板支架", "支撑架", "满堂支架"],
    "基坑": ["基坑", "深基坑", "边坡", "支护"],
    "起重吊装": ["起重", "吊装", "塔吊", "龙门吊"],
}


def filter_knowledge(project_type: str, metadata: dict | None = None,
                     knowledge_base: str | None = None) -> list[str]:
    """根据项目类型和元数据筛选知识库目录范围。"""
    metadata = metadata or {}
    base = knowledge_base or DEFAULT_KNOWLEDGE_BASE
    selected: list[str] = []

    type_dirs = PROJECT_TYPE_MAP.get(project_type, [])
    for d in type_dirs:
        path = os.path.join(base, d)
        if os.path.isdir(path):
            selected.append(path)

    for d in COMMON_DIRS:
        path = os.path.join(base, d)
        if os.path.isdir(path):
            selected.append(path)

    project_name = metadata.get("project_name", "")
    for subdir, keywords in KEYWORD_MAP.items():
        if any(kw in project_name for kw in keywords) and subdir not in type_dirs:
            for root_dir in selected + [base]:
                for dirpath, dirnames, _ in os.walk(root_dir):
                    if os.path.basename(dirpath) == subdir:
                        path = os.path.join(root_dir, subdir) if root_dir != dirpath else dirpath
                        if path not in selected:
                            selected.append(path)

    unique = list(dict.fromkeys(selected))

    if not unique:
        if os.path.isdir(base):
            unique = [base]
            logger.info(f"知识库筛选回退到根目录: {base}")
        else:
            logger.warning(f"知识库筛选无匹配结果且根目录不存在: path={base}")
    else:
        logger.info(f"知识库筛选结果 ({len(unique)} 个目录): {unique}")

    return unique


class ReviewKnowledgeProvider:
    """审查知识提供者（KnowledgeProvider 协议: scope(task_id, meta) → 知识范围）。"""

    def scope(self, task_id: str, meta: dict) -> list[str]:
        return filter_knowledge(meta.get("project_type", "other"), meta)
