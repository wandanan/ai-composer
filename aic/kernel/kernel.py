"""kit/kernel.py — agent-service-kit 内核 v0.1（M0 验证版）

协议执行机制，零业务：服务注册表 + 事件总线 + 可逆效果。
设计依据: docs/design/kernel-design.md 第五节。

M0 落地决策（与设计文档的差异）:
- 插件挂载采用「共享作用域 + 每插件效果桶」：所有插件 apply 进同一上下文，
  每个插件的注册由独立 bucket 记账，unmount 只撤销自己的（互不误伤）。
- 插件声明 `provides`（提供哪些服务 key）以支持 inject 拓扑装配；
  dsh 的"声明 inject 即等待"延迟装配留到 M1。
- fork()/子上下文隔离作用域 API 保留，M1 用于会话级 scope。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from typing import Any, Callable


class EventMode(StrEnum):
    """事件派发模式（dsh 四种模式的 Python 版）。"""

    EMIT = "emit"            # 观察: 监听器按注册顺序执行, 不等待, 无返回值
    WATERFALL = "waterfall"  # 中间件: handler(payload, next); 不调 next() 即短路
    PARALLEL = "parallel"    # 扇出: 并发执行
    SERIAL = "serial"        # 顺序加工: 返回值传给下一个监听器


class ServiceNotFound(KeyError):
    """按 key 查找服务失败。"""


Disposer = Callable[[], None]


class PluginMount:
    """一次插件挂载的记账单元（unmount 撤销该插件全部效果）。"""

    __slots__ = ("plugin", "_bucket")

    def __init__(self, plugin: Any, bucket: list[Disposer]):
        self.plugin = plugin
        self._bucket = bucket


class Context:
    """协议执行机制。

    - 服务: register/get，同 key 后注册覆盖；dispose 只撤销自己安装的实现
    - 事件: on/emit，单事件单一派发模式（模式是事件公共契约的一部分）
    - 挂载: mount(plugin) 效果入插件桶；unmount 逆序撤销，零残留
    """

    def __init__(self, parent: "Context | None" = None):
        self._services: dict[str, Any] = {}
        self._listeners: dict[str, dict] = {}   # event -> {mode, handlers[]}
        self._effects: list[Disposer] = []      # 平台层效果（非插件挂载时注册的）
        self._parent = parent
        self._current_bucket: list[Disposer] | None = None
        self._mount_audit: list[str] | None = None  # 挂载期间 register 的 key（能力面校验用）

    # ── ① 服务协议 ─────────────────────────────────────

    def register(self, key: str, impl: Any) -> Disposer:
        """注册服务。同 key 后注册覆盖先注册；返回 disposer 可手动注销。"""
        self._services[key] = impl
        if self._mount_audit is not None:
            self._mount_audit.append(key)   # 挂载期间记账 → mount 后能力面校验

        def _dispose():
            # 只撤销自己安装的实现：若已被其他插件覆盖则不动
            if self._services.get(key) is impl:
                self._services.pop(key, None)

        self.effect(_dispose)
        return _dispose

    def get(self, key: str) -> Any:
        """按协议查找服务实现（消费者不 import 实现，只依赖协议）。"""
        if key in self._services:
            return self._services[key]
        if self._parent is not None:
            return self._parent.get(key)
        raise ServiceNotFound(f"服务未注册: {key}")

    def has(self, key: str) -> bool:
        if key in self._services:
            return True
        return self._parent is not None and self._parent.has(key)

    # ── ② 事件协议 ─────────────────────────────────────

    def on(self, event: str, handler: Callable, mode: EventMode = EventMode.EMIT) -> Disposer:
        """注册事件监听。事件的派发模式由首次注册决定，之后必须一致。"""
        slot = self._listeners.setdefault(event, {"mode": None, "handlers": []})
        if slot["mode"] is None:
            slot["mode"] = mode
        elif slot["mode"] != mode:
            raise ValueError(f"事件 {event!r} 已声明为 {slot['mode']}，不能注册 {mode}")
        slot["handlers"].append(handler)

        def _dispose():
            try:
                slot["handlers"].remove(handler)
            except ValueError:
                pass

        self.effect(_dispose)
        return _dispose

    def emit(self, event: str, payload: Any = None) -> Any:
        """按事件声明的模式派发，返回最终 payload（waterfall/serial 可被改写）。"""
        slot = self._listeners.get(event)
        if not slot or not slot["handlers"]:
            return payload
        mode = slot["mode"]
        handlers = list(slot["handlers"])

        if mode == EventMode.EMIT:
            for handler in handlers:
                handler(payload)
            return payload

        if mode == EventMode.WATERFALL:
            # 中间件链: handler(payload, next); 未调 next() → 短路（决策生效）
            def _chain(i: int, current: Any) -> Any:
                if i >= len(handlers):
                    return current
                state = {"delegated": False, "value": current}

                def _next(wrapped: Any = None) -> Any:
                    state["delegated"] = True
                    state["value"] = _chain(i + 1, wrapped if wrapped is not None else current)
                    return state["value"]

                result = handlers[i](current, _next)
                if state["delegated"]:
                    return state["value"]
                return result if result is not None else current

            return _chain(0, payload)

        if mode == EventMode.PARALLEL:
            with ThreadPoolExecutor(max_workers=max(1, len(handlers))) as ex:
                futures = [ex.submit(handler, payload) for handler in handlers]
                for future in futures:
                    future.result()
            return payload

        # SERIAL: 顺序加工，返回值传递给下一个
        current = payload
        for handler in handlers:
            result = handler(current)
            if result is not None:
                current = result
        return current

    # ── ③ 挂载/卸载（自动销毁单元）────────────────────

    def mount(self, plugin: Any) -> PluginMount:
        """挂载插件：apply() 中的一切注册进入插件效果桶。

        挂载后做能力面校验（病毒检测，双向核对）:
          - 未声明注册: apply 里 register 了 provides 没声明的 key → 偷偷提供能力
          - 声明未注册: provides 声明了但 apply 没 register → 承诺了不兑现
        任一违规在装配时直接报错——插件进不来，而不是运行期才炸。
        """
        bucket: list[Disposer] = []
        audit: list[str] = []
        previous = self._current_bucket
        prev_audit = self._mount_audit
        self._current_bucket = bucket
        self._mount_audit = audit
        try:
            plugin.apply(self)
            # 能力面校验（病毒检测, 双向核对）——失败走同一撤销路径, 不留半挂
            declared = set(getattr(plugin, "provides", []) or [])
            registered = set(audit)
            problems: list[str] = []
            if undeclared := registered - declared:
                problems.append(f"未声明注册: {sorted(undeclared)}（provides 未声明这些 key）")
            if unregistered := declared - registered:
                problems.append(f"声明未注册: {sorted(unregistered)}（provides 声明了但 apply 未注册）")
            if problems:
                raise RuntimeError(
                    f"[kernel] 插件 {plugin.__class__.__name__} 能力面不一致: "
                    + "; ".join(problems))
        except Exception:
            # 装配失败：撤销本插件已注册的部分效果，不留半挂插件
            for fn in reversed(bucket):
                try:
                    fn()
                except Exception:
                    pass
            raise
        finally:
            self._current_bucket = previous
            self._mount_audit = prev_audit
        return PluginMount(plugin, bucket)

    def unmount(self, mount: PluginMount) -> None:
        """卸载插件：逆序撤销该插件全部效果（服务/监听），零残留。"""
        for fn in reversed(mount._bucket):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 — 撤销失败不阻断其余
                print(f"[kernel] 效果撤销失败: {exc}")  # TODO(M1): 接入 telemetry
        mount._bucket.clear()

    def fork(self) -> "Context":
        """子上下文（隔离作用域）。M1 预留：会话级 scope / 覆盖隔离。"""
        return Context(parent=self)

    # ── ④ 可逆效果 ─────────────────────────────────────

    def effect(self, disposer: Disposer) -> None:
        """注册可逆效果。挂载期间的注册自动入插件桶，否则入平台层。"""
        if self._current_bucket is not None:
            self._current_bucket.append(disposer)
        else:
            self._effects.append(disposer)


def build_dependency_graph(plugins: list[Any]) -> dict[Any, list[Any]]:
    """建依赖图: plugin -> 其 inject 的 key 的提供者列表。

    依赖是声明出来的元数据（inject/provides），一次读入内存成图——
    拓扑装配与撤销影响分析共用这一张图。
    """
    provided_by: dict[str, list[Any]] = {}
    for plugin in plugins:
        for key in getattr(plugin, "provides", []):
            provided_by.setdefault(key, []).append(plugin)

    deps: dict[Any, list[Any]] = {}
    for plugin in plugins:
        deps[plugin] = [
            provider
            for key in getattr(plugin, "inject", [])
            for provider in provided_by.get(key, [])
            if provider is not plugin
        ]
    return deps


def boot(root: Context, plugins: list[Any]) -> list[PluginMount]:
    """拓扑装配：按 inject 依赖自动推导挂载顺序；检测依赖环；校验 inject 契约。

    返回各插件的 PluginMount（供后续 unmount）。
    """
    deps = build_dependency_graph(plugins)

    order: list[Any] = []
    visited: set[Any] = set()

    def visit(plugin: Any, stack: set[Any]) -> None:
        if plugin in visited:
            return
        if plugin in stack:
            chain = [p.__class__.__name__ for p in stack] + [plugin.__class__.__name__]
            raise RuntimeError(f"插件依赖环: {' -> '.join(chain)}")
        stack.add(plugin)
        for provider in deps[plugin]:
            visit(provider, stack)
        stack.discard(plugin)
        visited.add(plugin)
        order.append(plugin)

    for plugin in plugins:
        visit(plugin, set())

    mounts = [root.mount(plugin) for plugin in order]

    # inject 契约校验: 装配完成后, 每个插件的 inject key 必须已被提供
    # （壳 pre-boot 注册 或 某插件 provides）——否则运行期 get 才炸, 违背"大声失败"。
    problems = [
        f"{plugin.__class__.__name__} inject 的 key 无人提供: {key!r}"
        for plugin in plugins
        for key in (getattr(plugin, "inject", []) or [])
        if not root.has(key)
    ]
    if problems:
        for m in reversed(mounts):   # 逆序撤销已挂载效果, 不留半挂装配
            root.unmount(m)
        raise RuntimeError("[kernel] 插件 inject 契约违规: " + "; ".join(problems))

    return mounts


def direct_dependents(plugins: list[Any], plugin: Any) -> set[Any]:
    """直接依赖方：撤销 plugin 直接伤到的插件（它们的 inject 与它的 provides 相交）。"""
    provided = set(getattr(plugin, "provides", []) or [])
    return {c for c in plugins
            if c is not plugin and (set(getattr(c, "inject", []) or []) & provided)}


def blast_radius(plugins: list[Any], plugin: Any) -> list[Any]:
    """撤销影响闭包（BFS 可达性）：直接 + 间接依赖 plugin 的全部插件。

    依赖图是显式可查询的——"撤销谁影响谁"在结构层面可计算，
    不必像传统代码那样靠 grep + 人肉 + 运行时测。
    """
    affected: set[Any] = set()
    frontier = direct_dependents(plugins, plugin)
    while frontier:
        c = frontier.pop()
        if c not in affected:
            affected.add(c)
            frontier |= direct_dependents(plugins, c)
    return list(affected)
