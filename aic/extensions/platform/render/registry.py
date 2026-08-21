"""kit/render/registry.py — 渲染注册表（ctx.renderers）。"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from aic.kernel import Context, Plugin


@runtime_checkable
class ArtifactRenderer(Protocol):
    """产物渲染器协议：把业务产物渲染为交付文件（docx/pdf/...）。

    0.2.1 形状泛化: 产物经 **artifacts 命名传递（业务自定义产物名,
    如 merged/outline）——平台不预定义业务产物形状。

    render 返回输出文件名（落盘到 session 工作区 output/ 目录）。
    """

    name: str

    def render(self, session: Any, *, version: int, **artifacts: str) -> str:
        """渲染产物到 session 工作区，返回输出文件名。"""
        ...


class RenderRegistry:
    """渲染注册表：业务插件注册渲染器，pipeline 按名调用。"""

    def __init__(self):
        self._renderers: dict[str, ArtifactRenderer] = {}

    def register(self, renderer: ArtifactRenderer) -> Callable[[], None]:
        """注册渲染器, 返回 disposer（插件 ctx.effect 登记 → unmount 撤销;
        同名替换恢复前一个——与 TaskRegistry 同语义）。"""
        previous = self._renderers.get(renderer.name)
        self._renderers[renderer.name] = renderer

        def _dispose():
            if previous is None:
                self._renderers.pop(renderer.name, None)
            else:
                self._renderers[renderer.name] = previous

        return _dispose

    def get(self, name: str) -> ArtifactRenderer:
        if name not in self._renderers:
            raise KeyError(f"渲染器未注册: {name}")
        return self._renderers[name]

    def has(self, name: str) -> bool:
        return name in self._renderers

    def names(self) -> list[str]:
        return list(self._renderers)


class RenderPlugin(Plugin):
    """渲染注册表插件：提供 ctx.renderers。"""

    provides = ["renderers"]

    def apply(self, ctx: Context):
        ctx.register("renderers", RenderRegistry())
