"""kit/render — 产物渲染扩展点（M3）。

平台定义 renderer 注册协议；业务插件注册自己的渲染器
（审查 = md 报告，编写 = docx 模板渲染），渲染阶段按需调用。
渲染器对平台是"可插拔能力"——协议稳定，实现可换。
"""
from .registry import ArtifactRenderer, RenderPlugin, RenderRegistry

__all__ = ["ArtifactRenderer", "RenderPlugin", "RenderRegistry"]
