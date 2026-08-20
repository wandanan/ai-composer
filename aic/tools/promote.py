"""tools/promote.py — 私有插件 → 公共插件（上浮命令）。

上浮 = 生命周期解绑（module-promotion.md 上浮原则的命令化）:
  ① 移动   插件包: 私有位（任意处）→ 公共惯例位（默认 extensions/platform/）
  ② 改引用 全项目 AST 扫描, 更新包外绝对 import（包内相对 import 随包移动无需改）
  ③ 写标记 插件类写入 PUBLIC = True —— uninstall 据此保留
            （公共插件有独立生命周期, 不随任何应用卸载删除）
  ④ 验证   剩余应用过壳布局契约

用法（默认预演: 只打印影响清单——将移动哪些目录、改哪些文件的 import、
PUBLIC 标记写进哪里——**不实际执行**; 上浮是破坏性操作（移动文件 + 改代码）,
先看清清单, 确认无误后加 --yes 真正执行）:
    python -m aic.tools.promote MyPlugin                 # 预演（默认）: 只看清单, 什么都不改
    python -m aic.tools.promote MyPlugin --yes           # 真正上浮（默认到 platform 公共惯例位）
    python -m aic.tools.promote MyPlugin --to business   # 上浮到领域惯例位（共享领域插件）
    python -m aic.tools.promote MyPlugin --to my_plugins # 上浮到隐式插件区任意目录
    例: python -m aic.tools.promote ReviewPlugin
        # → 显示: 移动 extensions/business/review → extensions/platform/review;
        #          更新 13 个文件的 import; 在 plugin.py 写 PUBLIC = True

KIT_PROJECT_ROOT 可指定项目根（测试模拟项目用）。
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shutil

from aic.tools.graph import _root, build_graph
from aic.tools.uninstall import _pkg_dir

# 地基: 插件不得进入的目录（kernel=机制 apps=壳 tools=工具）
_GROUND = ("aic", "apps")


def _module_pkg_prefix(root: str, module: str) -> str:
    """module 的包前缀（去掉模块文件尾段, 如 extensions.business.review.plugin
    → extensions.business.review; aic.extensions.platform.standard → 原样）。"""
    return os.path.relpath(_pkg_dir(root, module), root).replace(os.sep, ".")


def _iter_py(root: str):
    """遍历 root 下 apps/extensions/test 的 .py（排除 __pycache__）。"""
    for base in ("apps", "extensions", "test"):
        top = os.path.join(root, base)
        if not os.path.isdir(top):
            continue
        for dirpath, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs if d not in ("__pycache__",))
            for f in sorted(files):
                if f.endswith(".py"):
                    yield os.path.join(dirpath, f)


def _collect_refs(root: str, old_prefix: str) -> list[str]:
    """收集含旧包前缀绝对 import 的文件（AST 确认, 避免误替换注释/字符串）。"""
    refs: list[str] = []
    for path in _iter_py(root):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        hit = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                hit |= any(a.name == old_prefix
                           or a.name.startswith(old_prefix + ".")
                           for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                hit |= node.module == old_prefix \
                    or node.module.startswith(old_prefix + ".")
        if hit:
            refs.append(path)
    return refs


def _replace_refs(path: str, old: str, new: str) -> int:
    """文本替换包前缀（带边界: 前缀后必须是 . 或结束）。返回替换次数。"""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    pattern = re.compile(r"\b" + re.escape(old) + r"(?![\w])")
    updated, n = pattern.subn(new, content)
    if n:
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
    return n


def _write_public(path: str, cls: str) -> bool:
    """插件类定义后写入 PUBLIC = True 标记。已有则跳过, 返回是否写入。"""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if "PUBLIC = True" in content:
        return False
    m = re.search(rf"^class {cls}\(.*\):", content, re.MULTILINE)
    if not m:
        return False
    insert = m.group(0) + "\n    PUBLIC = True  # 公共插件: 不随任何应用卸载删除（aic.tools.promote 写入）"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content[:m.start()] + insert + content[m.end():])
    return True


def _plugin_file(root: str, module: str) -> str:
    """插件类所在文件（module → .py 或 /__init__.py）。"""
    base = os.path.join(root, *module.split("."))
    for candidate in (base + ".py", os.path.join(base, "__init__.py")):
        if os.path.isfile(candidate):
            return candidate
    return base + ".py"


def _resolve_target(root: str, to: str, src_pkg: str) -> str:
    """解析目标目录: platform/business 惯例位 或 隐式插件区任意相对路径。"""
    pkg_name = os.path.basename(src_pkg)
    if to in ("platform", "business"):
        base = os.path.join(root, "extensions", to)
    else:
        base = os.path.join(root, to)
    target = os.path.join(base, pkg_name)
    rel = os.path.relpath(target, root)
    if rel.split(os.sep)[0] in _GROUND:
        raise SystemExit(f"❌ 插件不得进入地基目录: {_GROUND}（target={rel}）")
    return target


def promote(root: str, graph: dict, cls: str, to: str,
            dry: bool) -> dict:
    """上浮影响分析 + 执行（dry=False 时）。返回报告 dict。"""
    if cls not in graph["plugins"]:
        raise SystemExit(f"❌ 未找到插件: {cls}")
    info = graph["plugins"][cls]
    module = info["module"]
    old_prefix = _module_pkg_prefix(root, module)
    src_pkg = _pkg_dir(root, module)
    if src_pkg.startswith(os.path.join(root, "aic")):
        raise SystemExit(
            f"❌ 框架插件（aic 内）不可上浮: {cls}——上浮只对用户空间插件（根 extensions/）; "
            f"框架平台是只读的（0.2.0 命名空间模型）")
    target = _resolve_target(root, to, src_pkg)

    if os.path.normpath(src_pkg) == os.path.normpath(target):
        # 已在目标位置: 幂等——只补 PUBLIC 标记
        pfile = _plugin_file(root, module)
        wrote = not dry and _write_public(pfile, cls)
        return {"already": True, "class": cls, "file": pfile,
                "marker": wrote or ("已存在" if not dry else "预演将跳过")}

    new_prefix = os.path.relpath(target, root).replace(os.sep, ".")
    refs = _collect_refs(root, old_prefix)
    pfile = _plugin_file(root, module)

    report = {
        "class": cls,
        "module": module,
        "move": (src_pkg, target),
        "refs": refs,
        "marker_file": pfile,
        "already": False,
    }
    if dry:
        return report

    # ① 改引用（先于移动: 源文件还在原位置）
    for path in refs:
        _replace_refs(path, old_prefix, new_prefix)
    # ② 移动包
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(src_pkg, target)
    # ③ 写 PUBLIC 标记（移动后路径）
    moved_file = os.path.join(target, os.path.relpath(pfile, src_pkg))
    report["marker_written"] = _write_public(moved_file, cls)
    return report


def _verify(graph: dict) -> list[str]:
    """上浮后验证: 剩余应用过壳布局契约（存在性 + 内容 AST）。"""
    from aic.kernel import check_shell_content, check_shell_layout
    root = _root()
    problems: list[str] = []
    for app in graph["apps"]:
        app_dir = os.path.join(root, "apps", app)
        if not os.path.isdir(app_dir):
            continue
        for check in (check_shell_layout, check_shell_content):
            try:
                check(app_dir)
            except RuntimeError as e:
                problems.append(f"{app}: {e}")
    return problems


def _render(report: dict, dry: bool) -> str:
    lines: list[str] = []
    if report.get("already"):
        lines.append(f"== 上浮 {report['class']}: 已在目标位置 ==")
        lines.append(f"  类文件: {report['file']}")
        lines.append(f"  PUBLIC 标记: {report['marker']}")
        return "\n".join(lines)
    lines.append(f"== 上浮 {report['class']}（{report['module']}）==")
    lines.append(f"  移动: {report['move'][0]}")
    lines.append(f"    →  {report['move'][1]}")
    lines.append(f"  引用更新: {len(report['refs'])} 个文件"
                 f"（{', '.join(os.path.relpath(p, _root()) for p in report['refs'][:8])}"
                 f"{'...' if len(report['refs']) > 8 else ''}）")
    lines.append(f"  PUBLIC 标记: 写入 {report['marker_file']}")
    lines.append("")
    if dry:
        lines.append("（预演: 未实际执行, 确认后加 --yes）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="aic promote",
        description="私有插件 → 公共插件（上浮命令）: 移动包到公共位 + 更新全项目"
                    " import 引用 + 写入 PUBLIC 标记（此后不随任何应用卸载删除）。"
                    " 默认只显示影响清单（预演）, 加 --yes 才真正执行。")
    p.add_argument("plugin", help="插件类名（如 ReviewPlugin）")
    p.add_argument("--to", default="platform",
                   help="目标惯例位: platform（公共, 默认）/ business（共享领域）/ 任意相对路径")
    p.add_argument("--yes", action="store_true",
                   help="确认清单后真正执行（移动文件 + 改 import + 写标记; 默认只预演）")
    args = p.parse_args(argv)

    root = _root()
    graph = build_graph()
    report = promote(root, graph, args.plugin, args.to, dry=not args.yes)
    print(_render(report, dry=not args.yes))

    if not args.yes:
        return
    if report.get("already"):
        print("\n✅ 上浮完成（已在目标位置, 仅确认标记）。")
        return
    problems = _verify(graph)
    if problems:
        print("\n⚠️ 上浮后验证未通过:")
        for msg in problems:
            print(f"  {msg}")
        raise SystemExit(1)
    print("\n✅ 上浮完成: 包已移动、引用已更新、PUBLIC 标记已写入。"
          "\n   （在各应用 profile 挂载即可共享; 卸载应用时该插件保留, 可单独 uninstall --plugin）")


if __name__ == "__main__":
    main()
