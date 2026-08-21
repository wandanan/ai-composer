"""aic.kernel — AIComposer 内核（零业务机制层）。

三层模型：框架（本包） + 业务插件 + 应用壳。
- 内核: Context（服务注册表/事件总线/挂载卸载）+ 契约检查
- 插件: 业务能力包（inject/provides/apply）
- 应用壳: 组合平台与插件并启动（见 test/m0_main.py）
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
from .imports import check_bypass_imports
from .layout import check_shell_content, check_shell_layout
from .plugin import Plugin

__version__ = "0.2.1.post2"

__all__ = [
    "Context",
    "EventMode",
    "Plugin",
    "PluginMount",
    "ServiceNotFound",
    "blast_radius",
    "boot",
    "check_bypass_imports",
    "check_shell_content",
    "check_shell_layout",
    "direct_dependents",
]
