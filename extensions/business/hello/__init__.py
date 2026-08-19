"""extensions/business/hello — 最小业务插件模板（新开发者上手用）。

复制本目录改造为你的业务:
  1. 重命名目录 hello → 你的业务名（如 review）
  2. 按「插件设计三步法」填充（① 能力 ② 流程 ③ 声明, 见 docs/design/business-organization.md）
  3. 在 apps/ 应用壳的 profile.py 里挂载: from extensions.business.hello import HelloPlugin
"""
from .plugin import HelloPlugin

__all__ = ["HelloPlugin"]
