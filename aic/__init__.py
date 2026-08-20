"""aic — AIComposer 统一入口（0.2.0 命名空间重构）。

框架包全部在 aic/ 下（kernel/ extensions/ apps/ tools/），发布包只装 aic*——
用户业务平铺在项目根（apps/ + extensions/business/），与框架命名空间互不冲突。

两种导入并存（等价）:
    from aic import Context, boot, Plugin        # 统一入口（品牌名）
    from aic.kernel import Context, boot         # 显式内核路径

组合式开发路径（模板/教程/生成代码）:
    from aic.extensions.platform.base import StoragePlugin   # 平台插件
    from apps.mine.profile import PLUGINS                    # 用户应用（平铺）
    from extensions.business.mine import MinePlugin          # 用户业务插件（平铺）
"""
from .kernel import (
    Context,
    EventMode,
    Plugin,
    PluginMount,
    ServiceNotFound,
    blast_radius,
    boot,
    check_bypass_imports,
    check_shell_content,
    check_shell_layout,
    direct_dependents,
)
from .kernel import __version__, imports, layout

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
