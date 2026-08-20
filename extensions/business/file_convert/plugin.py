"""extensions/business/file_convert/plugin.py — 文件格式转换（非 AI 业务插件）。

按「插件设计三步法」组织（docs/design/business-organization.md）:
  ① 能力:   ConverterService（普通服务, 不调 LLM）
  ② 流程:   ConvertPipeline（校验→转换→产物落盘）
  ③ 声明:   FileConvertPlugin（provides: converter / convertPipeline）
调用契约（运行时, 非设计步骤）:
  输入: 会话 meta = {job: "convert"}（一次转换任务 = 一个会话）
  输出: 转换文件 → 产物通道（output/{n}.{dst_type}, 版本化）
"""
import csv
import io
import json

from aic.kernel import Context, Plugin, ServiceNotFound
from aic.extensions.platform.session.artifacts import save_artifact


class ConverterService:
    """③ 能力: 格式转换（txt→md / csv→json, 普通服务）。"""

    def convert(self, content: str, src_type: str, dst_type: str) -> str:
        if (src_type, dst_type) == ("txt", "md"):
            return self._txt_to_md(content)
        if (src_type, dst_type) == ("csv", "json"):
            return self._csv_to_json(content)
        raise ValueError(f"不支持的转换: {src_type}→{dst_type}")

    @staticmethod
    def _txt_to_md(content: str) -> str:
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        parts = []
        for ln in lines:
            # 短行视为标题, 其余为正文段（演示用规则）
            parts.append(f"## {ln}" if len(ln) < 20 else ln)
        return "\n\n".join(parts)

    @staticmethod
    def _csv_to_json(content: str) -> str:
        rows = list(csv.DictReader(io.StringIO(content)))
        return json.dumps(rows, ensure_ascii=False, indent=2)


class ConvertPipeline:
    """④ 流程: 校验参数 → 调用能力 → 产物落盘（产物即接口）。"""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def run(self, session, content: str, src_type: str, dst_type: str) -> dict:
        svc = self.ctx.get("converter")          # 能力经协议取（不 import 实现）
        result = svc.convert(content, src_type, dst_type)

        name = f"output_{session.turn + 1}.{dst_type}"
        save_artifact(session.dir, "output", name, result)
        self.ctx.emit("convert/done", {"session_id": session.session_id,
                                       "output": name})

        return {"output": name, "chars": len(result), "dst_type": dst_type}


class FileConvertPlugin(Plugin):
    """⑤ 插件声明: 提供转换能力 + 流程。"""

    inject: list[str] = []                      # 需要什么（无需平台服务）
    provides: list[str] = ["converter", "convertPipeline"]   # 提供什么

    def apply(self, ctx: Context):
        ctx.register("converter", ConverterService())
        ctx.register("convertPipeline", ConvertPipeline(ctx))

        # 事件契约（0.2.1 事件注册表）: 业务事件声明 + SSE 桥接
        ctx.register_event("convert/done", {"session_id", "output"})
        try:
            ctx.get("stream").bridge("convert/done")
        except ServiceNotFound:
            pass
