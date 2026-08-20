"""kit/plugin.py — 业务插件基类。

业务即插件：审查 = review 插件，编写 = writer 插件，新业务 = 新插件。
插件声明依赖(inject)/提供能力(provides)，apply() 中注册服务/监听/效果。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .kernel import Context


class Plugin:
    """业务插件基类。

    子类实现:
      inject:   list[str] — 依赖的服务 key（内核自动推导装配顺序）
      provides: list[str] — 提供的服务 key（供其他插件依赖）
      apply(ctx)          — 注册服务/监听/效果（一切注册自动可逆）
    """

    inject: list[str] = []
    provides: list[str] = []

    def apply(self, ctx: "Context") -> None:
        raise NotImplementedError
