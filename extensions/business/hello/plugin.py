"""extensions/business/hello/plugin.py — 最小业务插件模板（约 30 行）。

演示新开发者心智模型:
  - 提供业务能力 → 实现协议形状（AgentTask）
  - 插件入口 → 声明 inject（需要什么）/ provides（提供什么）
  - 消费平台能力 → ctx.get(key) 协议调用（本模板未用, 见 writer 插件实例）
"""
from aic.kernel import Context, Plugin
from aic.extensions.platform.agent import AgentTask, Phase


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

    inject: list[str] = ["tasks"]     # 任务注册表（聚合键: 登记而非覆盖）
    provides: list[str] = ["hello"]   # 提供什么（能力面）

    def apply(self, ctx: Context):
        # 聚合键范式: 任务登记进平台注册表（effect 记账, unmount 撤销）,
        # 不再 ctx.register("tasks", dict)——多插件共挂时 dict 互相覆盖
        ctx.effect(ctx.get("tasks").register(HelloTask()))
        ctx.register("hello", lambda: "hello from plugin")
