"""test/m5_main.py — M5 验证: 挂载校验 + 撤销影响分析（blast radius）。

依据: docs/feature/framework-engineering-model.md 第六/八节（"暂未实施"→ 已实施）。

验证项:
  1. 能力面校验正例: 声明 = 注册 → 装配通过
  2. 未声明注册（病毒: 偷偷注册 provides 外的 key）→ 装配报错 + 效果已撤销
  3. 声明未注册（承诺了不兑现）→ 装配报错 + 效果已撤销
  4. 真实插件装配回归（hello/todo/file_convert + 平台插件）
  5. blast_radius: 直接依赖 / 传递闭包（链式 + 双向）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import Context, Plugin, boot, blast_radius, direct_dependents

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name}")


# ── 1. 能力面校验正例 ─────────────────────────────

class GoodPlugin(Plugin):
    provides = ["a", "b"]

    def apply(self, ctx: Context):
        ctx.register("a", 1)
        ctx.register("b", 2)


def t01_valid_plugin() -> None:
    ctx = Context()
    boot(ctx, [GoodPlugin()])
    check("t01 合法插件（声明=注册）装配通过",
          ctx.get("a") == 1 and ctx.get("b") == 2)


# ── 2. 未声明注册（病毒）→ 报错 + 撤销 ──────────────

class SneakyPlugin(Plugin):
    provides = ["a"]

    def apply(self, ctx: Context):
        ctx.register("a", 1)
        ctx.register("b", 2)   # 病毒: provides 没声明 b


def t02_undeclared() -> None:
    ctx = Context()
    try:
        boot(ctx, [SneakyPlugin()])
        check("t02 未声明注册 → 装配报错", False)
    except RuntimeError as e:
        check("t02 未声明注册 → 装配报错", "未声明注册" in str(e))
        check("t02 失败后效果已撤销（无半挂）",
              not ctx.has("a") and not ctx.has("b"))


# ── 3. 声明未注册（承诺不兑现）→ 报错 + 撤销 ─────────

class OverPromisePlugin(Plugin):
    provides = ["a", "b"]

    def apply(self, ctx: Context):
        ctx.register("a", 1)   # 承诺了 b 但没注册


def t03_overpromise() -> None:
    ctx = Context()
    try:
        boot(ctx, [OverPromisePlugin()])
        check("t03 声明未注册 → 装配报错", False)
    except RuntimeError as e:
        check("t03 声明未注册 → 装配报错", "声明未注册" in str(e))
        check("t03 失败后效果已撤销", not ctx.has("a"))


# ── 4. 真实插件装配回归 ────────────────────────────

def t04_real_plugins() -> None:
    from extensions.business.file_convert import FileConvertPlugin
    from extensions.business.hello import HelloPlugin
    from extensions.business.todo import TodoPlugin
    from extensions.platform.base import StoragePlugin

    ctx = Context()
    boot(ctx, [StoragePlugin(), HelloPlugin(), TodoPlugin(), FileConvertPlugin()])
    check("t04 真实插件装配通过",
          ctx.has("storage") and ctx.has("todos") and ctx.has("tasks")
          and ctx.has("converter") and ctx.has("convertPipeline"))


# ── 5. blast_radius: 直接依赖 / 传递闭包 ────────────

def t05_blast_radius() -> None:
    class A(Plugin):
        provides = ["a"]
        def apply(self, ctx): ctx.register("a", 1)

    class B(Plugin):
        inject = ["a"]
        provides = ["b"]
        def apply(self, ctx): ctx.register("b", 2)

    class C(Plugin):
        inject = ["b"]
        def apply(self, ctx): pass

    plugins = [A(), B(), C()]
    a, b, c = plugins
    check("t05 direct_dependents(A) = {B}", direct_dependents(plugins, a) == {b})
    check("t05 blast_radius(A) = {B, C}", set(blast_radius(plugins, a)) == {b, c})
    check("t05 blast_radius(B) = {C}", set(blast_radius(plugins, b)) == {c})
    check("t05 blast_radius(C) = ∅", blast_radius(plugins, c) == [])


def t06_blast_radius_transit() -> None:
    """双向依赖（B/C 既消费又提供）: 撤销 A 传递影响 B→C→D。"""
    class A(Plugin):
        provides = ["a"]
        def apply(self, ctx): ctx.register("a", 1)

    class B(Plugin):
        inject = ["a"]
        provides = ["b"]
        def apply(self, ctx): ctx.register("b", 2)

    class C(Plugin):
        inject = ["b"]
        provides = ["c"]
        def apply(self, ctx): ctx.register("c", 3)

    class D(Plugin):
        inject = ["c"]
        def apply(self, ctx): pass

    plugins = [A(), B(), C(), D()]
    radius = {p.__class__.__name__ for p in blast_radius(plugins, plugins[0])}
    check("t06 传递闭包: blast_radius(A) = {B,C,D}", radius == {"B", "C", "D"})


def t07_inject_missing() -> None:
    """inject 契约: 装配完成后 key 无人提供 → 装配期报错（大声失败, 不等运行期 get）。"""
    class NeedsGhost(Plugin):
        inject = ["ghost"]
        provides = ["n"]
        def apply(self, ctx: Context):
            ctx.register("n", 1)

    ctx = Context()
    try:
        boot(ctx, [NeedsGhost()])
        check("t07 inject 未提供 key → 装配期报错", False)
    except RuntimeError as e:
        check("t07 inject 未提供 key → 装配期报错", "inject" in str(e) and "ghost" in str(e))
    check("t07 报错后无残留挂载", not ctx.has("n"))


def main() -> None:
    t01_valid_plugin()
    t02_undeclared()
    t03_overpromise()
    t04_real_plugins()
    t05_blast_radius()
    t06_blast_radius_transit()
    t07_inject_missing()
    print(f"\nM5 验证: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
