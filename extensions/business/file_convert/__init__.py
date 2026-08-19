"""extensions/business/file_convert — 文件格式转换业务插件（非 AI 应用示例）。

通用插件写法演示: 能力（ConverterService）+ 流程（ConvertPipeline）+ 接线（FileConvertPlugin）。
无 AI: 不调 LLM, 不实现 AgentTask——普通服务 + 产物。
"""
from .plugin import FileConvertPlugin

__all__ = ["FileConvertPlugin"]
