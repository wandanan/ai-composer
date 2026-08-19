"""plugins/writer — 编写业务插件（M1a 最小流水线验证）。

业务即插件：本包 = 施工方案编写业务，挂载到 agent-service-kit 平台即构成编写应用。
"""
from .plugin import WriterPlugin

__all__ = ["WriterPlugin"]
