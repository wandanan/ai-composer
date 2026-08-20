"""kit/render/registry.py — 渲染注册表（ctx.renderers）。"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

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

    def register(self, renderer: ArtifactRenderer) -> None:
        self._renderers[renderer.name] = renderer

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
