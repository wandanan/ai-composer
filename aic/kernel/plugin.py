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
      inject:   list[str] — 依赖的服务 key（内核自动推导装配顺序; 缺席装配失败）
      inject_optional: list[str] — 可选依赖（有提供者则排在其后, 缺席不报错;
                消费方 try/except ServiceNotFound 自行降级——声明后拓扑序仍有保证）
      provides: list[str] — 提供的服务 key（供其他插件依赖）
      apply(ctx)          — 注册服务/监听/效果（一切注册自动可逆）
    """

    inject: list[str] = []
    inject_optional: list[str] = []
    provides: list[str] = []

    def apply(self, ctx: "Context") -> None:
        raise NotImplementedError
