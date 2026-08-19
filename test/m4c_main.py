"""m4c_main.py — M4c 验证：任务队列（Celery）插件化。

运行: PYTHONIOENCODING=utf-8 python m4c_main.py
（全部确定性验证，无 API 成本）

验证项:
  [1] JobsPlugin 装配 + JobQueue 协议合规
  [2] ThreadJobQueue: 任务真实执行（注册/提交/取结果）
  [3] 实现替换: CeleryJobQueue 同协议注册, 消费方零改动
  [4] 降级: FailoverJobQueue 主队列不可用 → 备用队列执行成功
  [5] 可逆销毁: unmount 后 ctx.jobs 撤销零残留
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time

from kernel import Context, Plugin, ServiceNotFound, boot
from extensions.platform.base import CachePlugin, ConfigPlugin, StoragePlugin, TelemetryPlugin
from extensions.platform.base.jobs import (
    CeleryJobQueue,
    FailoverJobQueue,
    JobQueue,
    JobsPlugin,
    ThreadJobQueue,
)

_PASS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def _greet(name: str) -> str:
    time.sleep(0.02)
    return f"hello {name}"


def _add(a: int, b: int) -> int:
    return a + b


class JobConsumerPlugin(Plugin):
    """演示业务插件：依赖任务队列（调用时取纪律）。"""

    inject = ["jobs"]
    provides = ["jobDemo"]

    def apply(self, ctx: Context):
        def _submit(task_name: str, args: list) -> str:
            return ctx.get("jobs").enqueue(task_name, args=args, queue="review")
        ctx.register("jobDemo", _submit)


def main() -> int:
    print("=" * 64)
    print("M4c 验证: 任务队列（Celery）插件化")
    print("=" * 64)

    app = Context()
    thread_queue = ThreadJobQueue()
    thread_queue.register_task("greet", _greet)
    thread_queue.register_task("add", _add)
    mounts = boot(app, [JobsPlugin(impl=thread_queue), JobConsumerPlugin()])
    order = [m.plugin.__class__.__name__ for m in mounts]
    print(f"\n[1] 装配: {order}")
    check("JobsPlugin 先于消费插件挂载",
          order == ["JobsPlugin", "JobConsumerPlugin"], str(order))
    jobs = app.get("jobs")
    check("JobQueue 协议合规", isinstance(jobs, JobQueue), type(jobs).__name__)

    print("\n[2] ThreadJobQueue 任务真实执行")
    submit = app.get("jobDemo")
    tid = submit("greet", ["celery"])
    check("任务提交返回 task id", isinstance(tid, str) and len(tid) > 0, tid)
    check("任务结果正确（线程池真实执行）", jobs.result(tid) == "hello celery")
    tid2 = submit("add", [2, 3])
    check("任务参数传递", jobs.result(tid2) == 5)

    print("\n[3] 实现替换（ThreadJobQueue → CeleryJobQueue 同协议, 真实实现）")
    celery_queue = CeleryJobQueue(broker_url="redis://127.0.0.1:6399/1",
                                  connect_timeout=2.0)
    celery_disposer = app.register("jobs", celery_queue)
    check("Celery 适配器同协议注册（消费方零改动）",
          isinstance(app.get("jobs"), CeleryJobQueue))
    check("Celery 适配器 health=False（broker 不可用）",
          celery_queue.health() is False)
    try:
        submit("greet", ["celery"])   # 无 broker: 真实连接 → 快速失败
        failed_fast = False
    except Exception:
        failed_fast = True
    check("broker 不可用时 enqueue 快速失败（由 Failover 兜底, 不挂起）", failed_fast)

    print("\n[4] 降级矩阵（FailoverJobQueue: Celery 不可用 → 线程池兜底）")
    failover = FailoverJobQueue(primary=celery_queue, fallback=thread_queue)
    failover_disposer = app.register("jobs", failover)
    tid4 = submit("greet", ["fallback"])   # 消费方零改动
    check("主队列不可用 → 备用队列执行成功", failover.result(tid4) == "hello fallback")
    check("降级计数 = 1", failover.fallbacks == 1, f"降级 {failover.fallbacks} 次")

    print("\n[5] 可逆销毁")
    app.unmount(mounts[0])
    still = app.get("jobs")
    check("卸载 JobsPlugin 后: 替换的 Failover 队列仍在（dispose 守卫不误删他人覆盖）",
          isinstance(still, FailoverJobQueue), type(still).__name__)
    celery_disposer()      # 被覆盖的注册: 守卫跳过（当前值非 celery）
    failover_disposer()    # 撤销当前注册 → key 消失（单值注册表, 后者胜）
    try:
        app.get("jobs")
        jobs_gone = False
    except ServiceNotFound:
        jobs_gone = True
    check("撤销当前注册后 ctx.jobs 消失（零残留）", jobs_gone)
    app.unmount(mounts[1])
    try:
        app.get("jobDemo")
        demo_gone = False
    except ServiceNotFound:
        demo_gone = True
    check("卸载消费插件后服务撤销（零残留）", demo_gone)

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print("✅ M4c 全部通过 — 任务队列（Celery）可插件化, 降级矩阵成立")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
