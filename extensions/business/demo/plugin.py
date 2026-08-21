"""plugins/demo/plugin.py — 演示业务插件（M0）。

包含两个插件以验证 inject 自动装配：
- DemoPlugin: 提供 greeter 服务 + 一个 AgentTask + 事件监听
- EchoPlugin: 依赖 greeter（inject），提供 echo 服务
"""
from __future__ import annotations

from aic.kernel import Context, EventMode, Plugin
from aic.extensions.platform.agent import AgentTask, Phase


class Greeter:
    """演示服务：提供问候能力。"""

    def __init__(self, name: str):
        self._name = name

    def greet(self, who: str) -> str:
        return f"你好, {who}! (来自 {self._name})"

    def __repr__(self) -> str:
        return f"Greeter({self._name})"


class DemoTask:
    """最小 AgentTask 实现：演示任务协议。"""

    id = "demo-task"

    def build_system_prompt(self, ctx: Context) -> str:
        greeter = ctx.get("greeter")
        return f"[demo] 系统提示词, 问候: {greeter.greet('系统')}"

    def toolsets(self, phase: Phase) -> list[str]:
        return ["file", "context_engine"]

    def knowledge_scope(self, meta: dict) -> list[str]:
        return ["demo/knowledge"]

    def on_result(self, session, result):
        return {"demo_task": "ok"}


class DemoPlugin(Plugin):
    """演示插件：提供 greeter 服务 + 一个任务 + 事件监听。"""

    inject = ["config", "tasks"]    # 平台基础服务 + 任务注册表（聚合键）
    provides = ["greeter"]

    def apply(self, ctx: Context):
        cfg = ctx.get("config")   # ConfigService（双参: section/key）, 非 dict
        provider = cfg.get("llm", "LLM_PROVIDER", "unset")
        ctx.register("greeter", Greeter(f"demo-plugin[{provider}]"))
        # 聚合键范式: 任务登记进平台注册表（effect 记账, unmount 撤销）
        ctx.effect(ctx.get("tasks").register(DemoTask()))

        # 事件契约（0.2.1 事件注册表）: 演示事件声明（render/path 与 tasks/notify 为字符串 payload）
        for evt, fields in (("app/started", {"sid"}),
                            ("prompt/build", {"section", "sections"}),
                            ("render/path", set()),
                            ("tasks/notify", set())):
            ctx.register_event(evt, fields)

        # 观察型监听: emit 模式
        def _on_started(payload):
            print(f"    [emit] DemoPlugin 观察到 app/started: {payload}")
        ctx.on("app/started", _on_started, EventMode.EMIT)

        # 中间件拦截: waterfall 模式 — 向 prompt 注入一段内容
        def _inject_section(payload, next):
            print(f"    [waterfall] DemoPlugin 注入段: {payload['section']}")
            payload["sections"].append("demo 插件注入的安全规则段")
            return next(payload)
        ctx.on("prompt/build", _inject_section, EventMode.WATERFALL)


class EchoPlugin(Plugin):
    """依赖演示插件：验证 inject 自动装配顺序（DemoPlugin 先挂载）。"""

    inject = ["greeter"]          # 依赖 DemoPlugin 提供的服务
    provides = ["echo"]

    def apply(self, ctx: Context):
        greeter = ctx.get("greeter")
        ctx.register("echo", lambda msg: greeter.greet(msg))
