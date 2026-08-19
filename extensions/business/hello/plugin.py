"""extensions/business/hello/plugin.py — 最小业务插件模板（约 30 行）。

演示新开发者心智模型:
  - 提供业务能力 → 实现协议形状（AgentTask）
  - 插件入口 → 声明 inject（需要什么）/ provides（提供什么）
  - 消费平台能力 → ctx.get(key) 协议调用（本模板未用, 见 writer 插件实例）
"""
from kernel import Context, Plugin
from kernel.protocols import AgentTask, Phase


class HelloTask:
    """① 能力: 业务能力定义（实现 AgentTask 协议形状, 或普通服务）。"""

    id = "hello"

    def build_system_prompt(self, ctx: Context) -> str:
        return "你是 hello 任务助手。"

    def toolsets(self, phase: Phase) -> list[str]:
        return []

    def knowledge_scope(self, meta: dict) -> list[str]:
        return []

    def on_result(self, session, result):
        return {"hello": True}


class HelloPlugin(Plugin):
    """③ 声明: 插件接线（依赖 inject + 能力面 provides）。"""

    inject: list[str] = []            # 需要什么（例: ["sessions", "renderers"]）
    provides: list[str] = ["tasks", "hello"]   # 提供什么（能力面）

    def apply(self, ctx: Context):
        ctx.register("tasks", {HelloTask.id: HelloTask()})
        ctx.register("hello", lambda: "hello from plugin")
