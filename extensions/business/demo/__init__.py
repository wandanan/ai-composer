"""plugins/demo — M0 演示业务插件。

验证「业务即插件」模型：挂载/依赖注入/事件监听/替换/销毁。
"""
from .plugin import DemoPlugin, EchoPlugin

__all__ = ["DemoPlugin", "EchoPlugin"]
