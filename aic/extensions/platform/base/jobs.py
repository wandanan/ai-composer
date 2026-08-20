"""kit/base/jobs.py — 任务队列基础设施插件（M4c）。

ctx.jobs: 任务队列协议（enqueue/result/health）。
- ThreadJobQueue:   线程池实现（验证/降级路径）——对应现有 _dispatch_background
- CeleryJobQueue:   Celery 适配器（真实实现: send_task 提交 + AsyncResult 取结果, broker 前置探测）
- FailoverJobQueue: 主队列不可用 → 备用队列（降级矩阵的插件表达）
对应 app/tasks/（celery_app + 降级线程池）的插件化。
"""
from __future__ import annotations

import importlib
import sys
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Protocol, runtime_checkable

from aic.kernel import Context, Plugin


@runtime_checkable
class JobQueue(Protocol):
    """任务队列协议。"""

    def register_task(self, name: str, fn: Callable) -> None:
        """注册任务（线程池登记 / Celery 任务装饰）。"""
        ...

    def enqueue(self, task_name: str, args: list | None = None,
                queue: str = "default") -> str:
        """提交任务，返回任务 id。"""
        ...

    def result(self, task_id: str, timeout: float | None = None) -> Any:
        """获取任务结果。"""
        ...

    def health(self) -> bool:
        """队列健康检查。"""
        ...


# ── 任务名协议守卫（机制强制）───────────────────────────
# 任务名 = 跨进程契约: shell 侧 register_task(name) 与 worker 侧
# @celery_app.task(name=...) 必须同名——send_task 按名分发, worker 侧无同名任务时
# 消息进 broker 后才 KeyError（静默失败）。守卫在每次注册时正向校验:
#   name ∈ apps.<app_pkg>.worker 模块内 @celery_app.task 注册的任务名
#   （模块命名空间扫描, 精确到本 worker——app.tasks 是进程级合并注册表, 不可用）
# 依据: docs/design/organization-contract.md（任务名协议）。

_WORKER_TASKS_CACHE: dict[str, frozenset[str] | None] = {}
_WARNED_DEGRADE: set[str] = set()


def _worker_task_names(app_pkg: str) -> frozenset[str] | None:
    """内省 apps.<app_pkg>.worker 模块内的 @celery_app.task 注册, 按 app_pkg memoize。

    用模块命名空间扫描（@app.task(name=...) 装饰后的对象带 .name/.apply/.run）,
    精确到本 worker 模块——Celery 的 app.tasks 是进程级合并注册表（多应用导入会
    互相污染）, 不能用。返回 None = worker 不可用（无法核对）→ 调用方降级跳过。
    仅 ImportError 降级（celery 未装/模块缺失）; worker.py 自身 bug 直接抛出（大声失败）。
    Celery() 构造不连 broker, import 安全。
    """
    if app_pkg in _WORKER_TASKS_CACHE:
        return _WORKER_TASKS_CACHE[app_pkg]
    try:
        worker = importlib.import_module(f"apps.{app_pkg}.worker")
    except ImportError:
        _WORKER_TASKS_CACHE[app_pkg] = None
        return None
    if getattr(worker, "celery_app", None) is None:  # 该应用不用 Celery → 无法核对, 降级
        _WORKER_TASKS_CACHE[app_pkg] = None
        return None
    names = frozenset(
        v.name for v in vars(worker).values()
        if isinstance(getattr(v, "name", None), str)
        and hasattr(v, "apply") and hasattr(v, "run")
    )
    _WORKER_TASKS_CACHE[app_pkg] = names
    return names


def _assert_registered_in_worker(app_pkg: str, name: str) -> None:
    """正向校验: 任务名必须在 worker 侧 celery_app.tasks 注册。违规 → RuntimeError。"""
    known = _worker_task_names(app_pkg)
    if known is None:
        if app_pkg not in _WARNED_DEGRADE:
            _WARNED_DEGRADE.add(app_pkg)
            print(f"[kernel] 任务名协议跳过校验: apps.{app_pkg}.worker 不可导入"
                  f"（celery 未装?）", file=sys.stderr)
        return
    if name not in known:
        raise RuntimeError(
            f"[kernel] 任务名协议违规: 任务 {name!r} 未在 apps.{app_pkg}.worker "
            f"的 celery_app.tasks 注册（可用: {sorted(known)}）")


class ThreadJobQueue:
    """线程池任务队列（本地实现/降级路径）。"""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._registry: dict[str, Callable] = {}
        self._results: dict[str, Future] = {}

    def register_task(self, name: str, fn: Callable) -> None:
        self._registry[name] = fn

    def enqueue(self, task_name: str, args: list | None = None,
                queue: str = "default") -> str:
        fn = self._registry[task_name]
        tid = uuid.uuid4().hex[:8]
        self._results[tid] = self._executor.submit(fn, *(args or []))
        return tid

    def result(self, task_id: str, timeout: float | None = None) -> Any:
        return self._results[task_id].result(timeout=timeout)

    def health(self) -> bool:
        return True


class CeleryJobQueue:
    """Celery 适配器（真实实现）：懒加载 celery_app，send_task 提交，AsyncResult 取结果。

    broker 不可用时 enqueue/health 抛错/返回 False——由 FailoverJobQueue 降级。
    _enqueued 保留提交审计日志（验证与可观测用）。
    """

    name = "celery"

    def __init__(self, broker_url: str = "redis://127.0.0.1:6379/1",
                 result_backend: str | None = None, connect_timeout: float = 2.0):
        self.broker_url = broker_url
        self._result_backend = result_backend or broker_url
        self._connect_timeout = connect_timeout
        self._app = None
        self._enqueued: list[tuple] = []

    def _get_app(self) -> Any:
        if self._app is None:
            from celery import Celery
            app = Celery("kit_jobs", broker=self.broker_url,
                         backend=self._result_backend)
            app.conf.update(task_serializer="json", accept_content=["json"],
                            result_serializer="json",
                            broker_connection_timeout=self._connect_timeout)
            self._app = app
        return self._app

    def register_task(self, name: str, fn: Callable) -> None:
        """把函数注册为 celery 任务（按名 send_task 提交, worker 侧同名任务执行）。"""
        self._get_app().task(name=name)(fn)

    def enqueue(self, task_name: str, args: list | None = None,
                queue: str = "default") -> str:
        # broker 前置探测: 不可达直接快速失败（kombu send_task 对黑洞端口会长时间挂起）
        if not self.health():
            raise ConnectionError(f"Celery broker 不可用: {self.broker_url}")
        result = self._get_app().send_task(task_name, args=args or [], queue=queue)
        self._enqueued.append((result.id, task_name, args or [], queue))
        return result.id

    def result(self, task_id: str, timeout: float | None = None) -> Any:
        if not self.health():
            raise ConnectionError(f"Celery broker 不可用: {self.broker_url}")
        return self._get_app().AsyncResult(task_id).get(timeout=timeout)

    def health(self) -> bool:
        """broker 连通性探测：原始 socket 连接（秒级确定, 不依赖 kombu 重试逻辑）。

        黑洞端口（SYN 丢弃）会使 kombu ensure_connection 挂起——socket 探测
        带显式 timeout, 保证 health 检查永远快速返回。
        """
        try:
            import socket
            from urllib.parse import urlsplit
            parts = urlsplit(self.broker_url)
            host = parts.hostname or "127.0.0.1"
            port = parts.port or 6379
            with socket.create_connection((host, port), timeout=2):
                return True
        except Exception:
            return False


class FailoverJobQueue:
    """任务队列降级：主队列不可用 → 备用队列（降级矩阵的插件表达）。"""

    name = "failover"

    def __init__(self, primary: JobQueue, fallback: JobQueue):
        self._primary = primary
        self._fallback = fallback
        self.fallbacks = 0

    def register_task(self, name: str, fn: Callable) -> None:
        self._primary.register_task(name, fn)
        self._fallback.register_task(name, fn)

    def enqueue(self, task_name: str, args: list | None = None,
                queue: str = "default") -> str:
        try:
            if not self._primary.health():
                raise ConnectionError("主队列不可用")
            return self._primary.enqueue(task_name, args, queue)
        except Exception:
            self.fallbacks += 1
            return self._fallback.enqueue(task_name, args, queue)

    def result(self, task_id: str, timeout: float | None = None) -> Any:
        for q in (self._primary, self._fallback):
            try:
                return q.result(task_id, timeout=timeout)
            except (KeyError, NotImplementedError, ConnectionError):
                continue
        raise KeyError(task_id)

    def health(self) -> bool:
        return self._primary.health() or self._fallback.health()


class _TaskNameGuardedQueue:
    """任务名协议守卫: 包装任意 JobQueue, register_task 前正向校验任务名。

    显式实现 JobQueue 的 4 个方法（不用 __getattr__ 委托）——runtime_checkable
    Protocol 的 isinstance 检查不破（m4c 协议合规测试兼容）。
    """

    def __init__(self, inner: JobQueue, app_pkg: str):
        self.impl = inner
        self._app_pkg = app_pkg

    def register_task(self, name: str, fn: Callable) -> None:
        _assert_registered_in_worker(self._app_pkg, name)  # 先校验后注册: 违规不产生半注册
        self.impl.register_task(name, fn)

    def enqueue(self, task_name: str, args: list | None = None,
                queue: str = "default") -> str:
        return self.impl.enqueue(task_name, args, queue)

    def result(self, task_id: str, timeout: float | None = None) -> Any:
        return self.impl.result(task_id, timeout=timeout)

    def health(self) -> bool:
        return self.impl.health()


class JobsPlugin(Plugin):
    """任务队列插件：提供 ctx.jobs。app_pkg 声明任务名协议（name ∈ worker.celery_app.tasks）。

    app_pkg=None（存量用法）→ 不包装, 零行为变化。
    """

    provides = ["jobs"]

    def __init__(self, impl: JobQueue | None = None, app_pkg: str | None = None):
        self._impl = impl
        self._app_pkg = app_pkg

    def apply(self, ctx: Context):
        queue = self._impl or ThreadJobQueue()
        if self._app_pkg:
            queue = _TaskNameGuardedQueue(queue, self._app_pkg)
        ctx.register("jobs", queue)
