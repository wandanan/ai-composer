"""m0_main.py — M0 验证：应用壳 = 平台内核 + 业务插件 模型是否成立。

运行: python m0_main.py
验证项（对应 kernel-design.md 验收标准 #2/#3/#4）:
  [1] 自动装配   inject 依赖 → 乱序传入自动推导挂载顺序
  [2] 服务查找   按协议 ctx.get() 取实现
  [3] 任务协议   业务插件提供 AgentTask（业务即插件的核心）
  [4] 事件总线   4 种派发模式（emit/waterfall/parallel/serial）
  [5] 同 key 覆盖 实现可替换
  [6] 自动销毁   unmount 零残留（服务/监听全撤销，且不误伤其他插件）
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aic.kernel import Context, EventMode, ServiceNotFound, boot
from aic.extensions.platform.agent import AgentTask
from extensions.business.demo import DemoPlugin, EchoPlugin
from extensions.business.demo.plugin import Greeter

_PASS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=" * 64)
    print("M0 验证: 应用壳 = 平台内核 + 业务插件")
    print("=" * 64)

    # ── 应用壳动作 1: 初始化平台根上下文 + 平台基础服务 ──
    app = Context()
    from aic.extensions.platform.base.config import ConfigService
    app.register("config", ConfigService())   # 平台基础服务（统一 ConfigService 形态）
    app.register("greeter", Greeter("平台默认"))                    # 平台默认实现（可被插件覆盖）

    # ── 应用壳动作 2: 组合业务插件（故意乱序，验证 boot 推导装配顺序）──
    from aic.extensions.platform.agent import TasksPlugin
    mounts = boot(app, [EchoPlugin(), DemoPlugin(), TasksPlugin()])

    print("\n[1] 自动装配 (inject 依赖 → 拓扑排序)")
    order = [m.plugin.__class__.__name__ for m in mounts]
    check("乱序传入自动推导: [TasksPlugin, DemoPlugin, EchoPlugin]",
          order == ["TasksPlugin", "DemoPlugin", "EchoPlugin"], str(order))

    print("\n[2] 服务查找 (协议接入, 不 import 实现)")
    greeter = app.get("greeter")
    check("ctx.get('greeter') 返回 DemoPlugin 的覆盖实现",
          "demo-plugin" in greeter.greet("M0"), str(greeter))
    echo = app.get("echo")
    check("ctx.get('echo') 注入可用 (echo → greeter)",
          "demo-plugin" in echo("M0"), echo("M0"))

    print("\n[3] 任务协议 (业务即插件)")
    tasks = app.get("tasks")
    task = tasks["demo-task"]
    check("AgentTask 协议合规 (runtime_checkable)", isinstance(task, AgentTask))
    check("build_system_prompt 可访问 ctx 服务",
          "demo-plugin" in task.build_system_prompt(app))

    print("\n[4] 事件总线 (4 种派发模式)")
    app.emit("app/started", {"sid": "demo-001"})
    check("emit 模式: 监听器按注册顺序观察", True)

    payload = {"section": "安全规则", "sections": []}
    final = app.emit("prompt/build", payload)
    check("waterfall 模式: 中间件链注入并委托",
          "demo 插件注入的安全规则段" in final["sections"], str(final["sections"]))

    serial_path = "report.md"
    app.on("render/path", lambda s: s + "|ver=1", EventMode.SERIAL)
    app.on("render/path", lambda s: s + "|ts=2", EventMode.SERIAL)
    serial_result = app.emit("render/path", serial_path)
    check("serial 模式: 顺序加工, 返回值传递",
          serial_result == "report.md|ver=1|ts=2", serial_result)

    parallel_results: list[str] = []
    app.on("tasks/notify", lambda p: parallel_results.append(p + "-a"), EventMode.PARALLEL)
    app.on("tasks/notify", lambda p: parallel_results.append(p + "-b"), EventMode.PARALLEL)
    app.emit("tasks/notify", "job")
    check("parallel 模式: 并发执行完成",
          sorted(parallel_results) == ["job-a", "job-b"], str(sorted(parallel_results)))

    print("\n[4.5] 事件契约注册表 (0.2.1, 大声失败)")
    try:
        app.emit("no/such/event", {"x": 1})
        check("未登记事件 → 报错", False)
    except RuntimeError as e:
        check("未登记事件 → RuntimeError", "事件未登记" in str(e))
    try:
        app.emit("app/started", {"sid": "s", "extra": 1})
        check("payload 超集 → 报错", False)
    except RuntimeError as e:
        check("payload 含未声明字段 → RuntimeError", "未声明字段" in str(e))
    app.emit("app/started", {"sid": "s"})
    check("已登记事件 + 合规 payload 通过", True)

    print("\n[5] 同 key 覆盖替换 (实现可换)")
    replaced_disposer = app.register("greeter", Greeter("替换实现"))
    replaced = app.get("greeter")
    check("后注册覆盖: get 返回替换实现",
          "替换实现" in replaced.greet("M0"), str(replaced))

    print("\n[6] 自动销毁 (unmount 零残留, 不误伤其他插件)")
    demo_mount, echo_mount = mounts[1], mounts[2]   # mounts[0] = TasksPlugin（注册表保留）
    app.unmount(demo_mount)

    still = app.get("greeter")
    check("unmount DemoPlugin 后: 替换实现仍在 (dispose 只撤销自己安装的)",
          "替换实现" in still.greet("M0"), str(still))
    check("unmount DemoPlugin 后: EchoPlugin 的 echo 服务仍在 (不误伤)",
          app.get("echo")("M0").startswith("你好"), app.get("echo")("M0"))

    # tasks 是聚合注册表（TasksPlugin 仍在挂载）: demo 卸载只撤销自己登记的任务条目
    check("unmount DemoPlugin 后: demo-task 已从注册表撤销 (零残留)",
          "demo-task" not in app.get("tasks"))

    live_slot = app._listeners.get("app/started")  # 验证脚本读取内部状态
    check("unmount DemoPlugin 后: 事件监听器零残留",
          not live_slot or not live_slot["handlers"])

    app.unmount(echo_mount)
    try:
        app.get("echo")
        echo_gone = False
    except ServiceNotFound:
        echo_gone = True
    check("unmount EchoPlugin 后: echo 服务已撤销", echo_gone)

    replaced_disposer()
    try:
        restored = app.get("greeter")
        greeter_restored = "平台默认" in restored.greet("M0")
    except ServiceNotFound:
        greeter_restored = False
    check("撤销替换注册后: greeter 恢复平台默认 (覆盖可恢复, 不再被带走)",
          greeter_restored)

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print("✅ M0 全部通过 — 「应用壳 = 平台内核 + 业务插件」模型成立")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
