"""extensions/business/todo — 待办管理业务插件（非 AI 应用示例, 纯数据服务型）。

无产物文件: 数据经 ctx.storage 协议存取（依赖注入演示）——与 AI 插件结构相同。
"""
from .plugin import TodoPlugin

__all__ = ["TodoPlugin"]
