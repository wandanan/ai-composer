"""biz/writer/knowledge.py — 编写知识注入（M3：模板/范例）。

实现 KnowledgeProvider 协议：按任务返回知识目录列表。
- templates/ 方案模板库（章节骨架/样式约定）—— 插件内置资源
- examples/ 优秀方案范例库 —— 插件内置资源（内容生产是业务投入重点, 逐步积累）
- standards/ 规范体系 —— 领域共享（引用审查应用的规范库, 未在本阶段接入）
"""
from __future__ import annotations

import os

from aic.kernel.protocols import KnowledgeProvider

_RESOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


class WritingKnowledgeProvider:
    """编写知识提供者：模板 + 范例目录。"""

    def scope(self, task_id: str, meta: dict) -> list[str]:
        return [
            os.path.join(_RESOURCES_DIR, "templates"),
            os.path.join(_RESOURCES_DIR, "examples"),
        ]
