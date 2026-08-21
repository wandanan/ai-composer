"""tools/uninstall.py — 应用/插件卸载（元命令, 自包含影响分析）。

影响分析直接计算（AST 扫描声明式元数据, 复用 aic.tools.graph.build_graph 函数,
不依赖任何命令的前置产物）——卸载是"算清楚再删", 不是 rm -rf。

用法:
    python -m aic.tools.uninstall my-app                     # 预演: 影响清单
    python -m aic.tools.uninstall my-app --yes               # 实际卸载（壳 + 专属插件）
    python -m aic.tools.uninstall --plugin DemoPlugin --yes  # 卸载插件包（无消费方闭包）

影响分析规则:
  - 应用卸载: 壳目录 + 专属插件（只挂载该应用, 且非动态）; 共享插件保留并列出
  - 插件卸载: 候选 = 插件类所在包的全部插件类（闭包内互相消费不算阻塞）;
    有挂载应用或包外消费方 → 拒绝并列出; 无 → 删除插件包
卸载后验证: 剩余应用跑壳布局契约（存在性 + 内容 AST 检查）。

KIT_PROJECT_ROOT 环境变量可指定项目根（测试模拟项目用, 默认本仓库）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _root() -> str:
    """项目根 = cwd（与 aic.tools.graph 一致; KIT_PROJECT_ROOT 测试覆盖）。"""
    return os.environ.get("KIT_PROJECT_ROOT") or os.getcwd()


def _pkg_dir(root: str, module: str) -> str:
    """插件类所在包目录（module 段逐级落目录, 模块文件尾段回退）。"""
    cur = root
    last_dir = root
    for seg in module.split("."):
        nxt = os.path.join(cur, seg)
        if os.path.isdir(nxt):
            last_dir = nxt
            cur = nxt
        else:
            break
    return last_dir


def _same_pkg(root: str, graph: dict, cls: str) -> list[str]:
    """与 cls 同包（模块目录相同）的插件类。"""
    pkg = _pkg_dir(root, graph["plugins"][cls]["module"])
    return sorted(
        c for c, i in graph["plugins"].items()
        if _pkg_dir(root, i["module"]) == pkg)


def analyze_app_removal(root: str, graph: dict, app: str) -> dict:
    """应用卸载影响: 删除清单（壳 + 专属插件）+ 保留清单（共享/动态插件）。"""
    if app not in graph["apps"]:
        return {"error": f"未找到应用壳: apps/{app}（现有: {', '.join(graph['apps'])}）"}
    mounts = sorted({e["to"] for e in graph["edges"]
                     if e["kind"] == "mount" and e["from"] == app})
    # 专属 = 只挂载该应用、非动态、且非公共（PUBLIC 标记的上浮插件有独立生命周期,
    # 不随应用卸载删除——如 ExtractPlugin 已上浮 platform 但只被 review 挂载）
    exclusive = [
        cls for cls in mounts
        if graph["plugins"][cls]["apps"] == [app]
        and not graph["plugins"][cls]["dynamic"]
        and not graph["plugins"][cls].get("public")]
    # 同包保护: 删除粒度是整包——专属插件的包内若混有共享/公共插件,
    # 整包不可删（会误删同包的他插件, 如 DbPlugin 与 StoragePlugin 同在 base 包）
    # → 降级为保留
    shared = [cls for cls in mounts if cls not in exclusive]
    safe_exclusive: list[str] = []
    for cls in exclusive:
        pkg_mates = _same_pkg(root, graph, cls)
        if all(c in exclusive for c in pkg_mates):
            safe_exclusive.append(cls)
        else:
            shared.append(cls)
    exclusive = sorted(safe_exclusive)
    shared = sorted(set(shared))

    delete = [os.path.join(root, "apps", app)] + [
        _pkg_dir(root, graph["plugins"][cls]["module"]) for cls in exclusive]
    return {
        "app": app,
        "delete": sorted(set(delete)),
        "exclusive_plugins": exclusive,   # 随应用一起删除
        "shared_plugins": shared,         # 保留: 其他应用仍在使用
    }


def analyze_plugin_removal(root: str, graph: dict, cls: str) -> dict:
    """插件卸载影响: 候选 = 同包插件闭包; 有包外消费方/挂载 → 拒绝。"""
    if cls not in graph["plugins"]:
        return {"error": f"未找到插件: {cls}"}

    candidates = _same_pkg(root, graph, cls)          # 同包全部插件类
    mounted = sorted({a for c in candidates
                      for a in graph["plugins"][c]["apps"]})   # 挂载候选的应用
    consumers = sorted(
        other for other, oi in graph["plugins"].items()
        if other not in candidates
        and any(set(graph["plugins"][c]["provides"]) & set(oi["inject"])
                for c in candidates))

    blocked: list[str] = []
    if mounted:
        blocked.append(f"挂载应用: {mounted}")
    if consumers:
        blocked.append(f"包外消费方: {consumers}")

    return {
        "plugin": cls,
        "package": _pkg_dir(root, graph["plugins"][cls]["module"]),
        "candidates": candidates,
        "blocked": blocked,
        "delete": [] if blocked else [_pkg_dir(root, graph["plugins"][cls]["module"])],
    }


def verify_remaining(graph: dict, removed_app: str | None) -> list[str]:
    """卸载后验证: 剩余应用过壳布局契约（存在性 + 内容 AST 检查）+ profile 可导入。

    profile 导入烟测: graph 的 AST 扫描是子集（条件追加/推导可能漏报挂载）,
    误删"看似专属"的插件时布局检查照绿——导入 profile 让断裂的引用大声暴露。
    """
    from aic.kernel import check_shell_content, check_shell_layout
    root = _root()
    if root not in sys.path:
        sys.path.insert(0, root)
    problems: list[str] = []
    for app in graph["apps"]:
        if app == removed_app:
            continue
        app_dir = os.path.join(root, "apps", app)
        if not os.path.isdir(app_dir):
            problems.append(f"{app}: 壳目录不存在（可能本就未落地）")
            continue
        for check in (check_shell_layout, check_shell_content):
            try:
                check(app_dir)
            except RuntimeError as e:
                problems.append(f"{app}: {e}")
        try:
            import importlib
            importlib.import_module(f"apps.{app}.profile")
        except Exception as e:  # noqa: BLE001 — 任何导入失败都要报（引用断裂）
            problems.append(f"{app}: profile 导入失败（可能引用了被删插件）: {e}")
    return problems


def _render(app_result: dict | None, plugin_result: dict | None,
            dry: bool, graph: dict) -> str:
    lines: list[str] = []
    if app_result is not None:
        if "error" in app_result:
            return f"❌ {app_result['error']}"
        lines.append(f"== 卸载应用: {app_result['app']} ==")
        lines.append(f"  删除: {len(app_result['delete'])} 项")
        for d in app_result["delete"]:
            lines.append(f"    - {d}")
        lines.append(f"  专属插件（随删）: {app_result['exclusive_plugins'] or '无'}")
        public_kept = [c for c in app_result['shared_plugins']
                       if graph["plugins"][c].get("public")]
        lines.append(f"  共享/公共插件（保留）: {app_result['shared_plugins'] or '无'}"
                     f"（其他应用仍在使用; 其中公共插件 {public_kept or '无'} 有独立生命周期,"
                     f" 可单独 uninstall --plugin）")
    if plugin_result is not None:
        if "error" in plugin_result:
            return f"❌ {plugin_result['error']}"
        lines.append(f"== 卸载插件: {plugin_result['plugin']} ==")
        lines.append(f"  候选（同包）: {plugin_result['candidates']}")
        if plugin_result["blocked"]:
            lines.append(f"  ❌ 拒绝卸载:")
            for b in plugin_result["blocked"]:
                lines.append(f"    - {b}")
            return "\n".join(lines)
        lines.append(f"  删除: {plugin_result['package']}")
    lines.append("")
    if dry:
        lines.append("（预演: 未实际删除, 确认后加 --yes）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="aic uninstall",
        description="应用/插件卸载（元命令, 影响分析后删除; 默认 预演 只出清单）")
    p.add_argument("target", nargs="?", help="应用名（apps/ 下的壳目录名）")
    p.add_argument("--plugin", metavar="CLASS", help="卸载插件类（连同其包）")
    p.add_argument("--yes", action="store_true", help="实际执行（默认 预演）")
    args = p.parse_args(argv)

    if not args.target and not args.plugin:
        raise SystemExit("用法: aic uninstall <应用名> [--yes]"
                         "  或  aic uninstall --plugin <类名> [--yes]")

    from aic.tools.graph import build_graph  # 元命令自包含: 直接计算, 不依赖产物
    graph = build_graph()
    root = _root()

    app_result = None
    plugin_result = None
    if args.target:
        app_result = analyze_app_removal(root, graph, args.target)
    if args.plugin:
        plugin_result = analyze_plugin_removal(root, graph, args.plugin)

    print(_render(app_result, plugin_result, dry=not args.yes, graph=graph))

    # 执行删除（默认 预演: 只打印清单）
    if not args.yes:
        return
    delete = (app_result or {}).get("delete", []) + (plugin_result or {}).get("delete", [])
    for d in sorted(set(delete)):
        if not d.startswith(root):
            raise SystemExit(f"❌ 拒绝删除项目根之外的路径: {d}")
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  删除: {d}")
        else:
            print(f"  跳过（不存在）: {d}")

    # 卸载后验证: 剩余应用过壳布局契约
    removed = app_result["app"] if app_result else None
    problems = verify_remaining(graph, removed)
    if problems:
        print("\n⚠️ 卸载后验证未通过:")
        for msg in problems:
            print(f"  {msg}")
        sys.exit(1)
    print("\n✅ 卸载完成, 剩余应用壳布局契约检查全部通过。")


if __name__ == "__main__":
    main()
