"""extensions/platform/security — 安全能力（沙箱插件）。

与业务安全约束彻底分离：
- 本包只做通用边界（文件访问/搜索限制），可被任意应用复用
- 业务约束归各业务插件自带
"""
from .sandbox import SandboxPlugin, SandboxService

__all__ = ["SandboxPlugin", "SandboxService"]
