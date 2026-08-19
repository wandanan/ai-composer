"""extensions/business/standard — 规范检索领域插件（review/writer 共享）。

原项目设计: standard_search 不适合各自实现两份 → 提炼为共享领域子插件
（见 writer-app-architecture: review 与 writer 共同挂载）。
"""
from __future__ import annotations

import os

from kernel import Context, Plugin

from extensions.business.standard.tool import StandardSearchTool


class StandardPlugin(Plugin):
    """规范检索插件：提供 ctx.standardSearch + 注册 hermes 工具 standard_search。"""

    PUBLIC = True   # 公共插件（领域共享: review/writer 共用）: 不随任何应用卸载删除
    provides = ["standardSearch"]

    def __init__(self, search_url: str = "", timeout: float = 5.0):
        self._search_url = search_url
        self._timeout = timeout

    def apply(self, ctx: Context):
        # hermes registry 由 import standard.tool 时模块级 _register() 触发（工具名 standard_search）
        tool = StandardSearchTool(
            self._search_url or os.environ.get("STANDARD_SEARCH_URL", ""),
            timeout=self._timeout)
        ctx.register("standardSearch", tool)


__all__ = ["StandardPlugin"]
