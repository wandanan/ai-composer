"""aic/extensions/platform/standard — 规范检索平台插件（0.2.0 上浮）。

原为领域共享插件（review/writer 共用）; 0.2.0 命名空间重构时上浮进平台
（hello_aic 模板基础依赖它, 且是通用检索能力——上浮三问: 会被替换/谁会用/拖垮宿主）。
"""
from __future__ import annotations

import os

from aic.kernel import Context, Plugin

from .tool import StandardSearchTool, register_standard_tool


class StandardPlugin(Plugin):
    """规范检索插件：提供 ctx.standardSearch + 注册 hermes 工具 standard_search。"""

    PUBLIC = True   # 公共插件（领域共享: review/writer 共用）: 不随任何应用卸载删除
    provides = ["standardSearch"]

    def __init__(self, search_url: str = "", timeout: float = 5.0):
        self._search_url = search_url
        self._timeout = timeout

    def apply(self, ctx: Context):
        # 同一实例两边登记: ctx 服务 + hermes 工具表（可逆, unmount 注销）
        tool = StandardSearchTool(
            self._search_url or os.environ.get("STANDARD_SEARCH_URL", ""),
            timeout=self._timeout)
        ctx.register("standardSearch", tool)
        dispose = register_standard_tool(tool)
        if dispose is not None:
            ctx.effect(dispose)


__all__ = ["StandardPlugin"]
