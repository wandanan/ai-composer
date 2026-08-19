"""agent-service-kit — 平台层（M0 验证版）。

三层模型：平台（本包） + 业务插件 + 应用壳。
- 平台: 内核（Context/事件总线/挂载卸载）+ 协议清单
- 插件: 业务能力包（审查/编写/未来业务）
- 应用壳: 组合平台与插件并启动（见 m0_main.py）
"""
from .kernel import (
    Context,
    EventMode,
    PluginMount,
    ServiceNotFound,
    blast_radius,
    boot,
    direct_dependents,
)
from .layout import check_shell_content, check_shell_layout
from .plugin import Plugin

__version__ = "0.1.0"

__all__ = [
    "Context",
    "EventMode",
    "Plugin",
    "PluginMount",
    "ServiceNotFound",
    "blast_radius",
    "boot",
    "check_shell_content",
    "check_shell_layout",
    "direct_dependents",
]
