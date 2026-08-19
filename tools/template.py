"""tools/template.py — 新应用开发模板提取（跨应用复用的核心用法）。

模板只带走**公共插件**（PUBLIC = True, 上浮过 = 你显式声明过独立生命周期）:
  基础 AIC（kernel/tools/m0 回归/requirements）+ 公共插件包 + 示例壳 hello_aic
  + docs/learn —— 不复制任何私有业务（模板永远不是旧应用的复制品）。

规则: 想把什么带进模板 → 先 promote（python -m tools.promote XxxPlugin --yes）
     template 只执行你的上浮声明; 未上浮的插件（即使多应用挂载）不带走,
     只列出提示。复制粒度为插件包（包完整性优先, 包内未上浮插件不挂载）。

用法:
    python -m tools.template review                 # 预演: 清单
    python -m tools.template review --out ~/my-tpl  # 提取到指定目录
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys

from tools.graph import _root, build_graph
from tools.uninstall import _pkg_dir

# 模板包含的基础层（目录/文件白名单）
# loops（引擎）是基础 AIC 的一部分: 所有 shell 硬编码引用 FakeLoop/HermesEnginePlugin
# skills（.claude/.codex/.agent）: 模板项目自带范式开发指导（约束/规范/命令速查）
_BASE_DIRS = ("kernel", "tools", "extensions/platform/loops",
              ".claude/skills", ".codex/skills", ".agent/skills")
_BASE_FILES = ()
_DOCS_LEARN = "docs/learn"

# 第三方包: import 名 → requirements 包名（import 名 ≠ 包名的映射, 如 fitz→pymupdf）
_IMPORT_TO_PKG = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "celery": "celery",
    "redis": "redis", "docx": "python-docx", "pydantic": "pydantic",
    "sqlalchemy": "sqlalchemy", "pymysql": "pymysql", "fitz": "pymupdf",
    "multipart": "python-multipart",
}

# 运行必需但代码不 import（启动器 uvicorn / fastapi 传递依赖 pydantic）: 强制保留
_MANDATORY_PKGS = ("uvicorn", "pydantic")


def _scan_imports(template_dir: str) -> set[str]:
    """AST 扫描模板所有 .py 的顶层 import 模块名（第一段）。"""
    tops: set[str] = set()
    for root, dirs, files in os.walk(template_dir):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__",))
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        tops.add(a.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    tops.add(node.module.split(".")[0])
    return tops


def _generate_requirements(out_dir: str, src_req: str) -> None:
    """模板 requirements: 从模板代码 import 反推, 只保留实际用到的依赖。

    源项目的 python-docx（writer 渲染）/python-multipart（review 上传）等
    业务专属依赖不会被带入模板——模板是地基, 按需自加。
    """
    imports = _scan_imports(out_dir)
    needed = sorted({pkg for imp, pkg in _IMPORT_TO_PKG.items()
                     if imp in imports} | set(_MANDATORY_PKGS))

    # 版本约束从源 requirements 继承（保留原行: fastapi>=0.110）
    constraints: dict[str, str] = {}
    for line in open(src_req, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if m:
            constraints[m.group(1)] = line[len(m.group(1)):]

    lines = [
        "# ai-composer 模板依赖（tools.template 自动生成: 按模板实际 import 过滤）",
        "# 内核纯标准库零依赖; 以下为公共插件 + hello_aic 实际需要的依赖",
    ]
    lines += [f"{pkg}{constraints.get(pkg, '')}" for pkg in needed]
    with open(os.path.join(out_dir, "requirements.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

# 模板自带自检（与模板自洽——源项目的 m0~m7 绑定了具体业务插件, 不适合进模板）
_TEMPLATE_CHECK = '''"""test/template_check.py — 模板自检（tools.template 生成）。

验证模板自洽: 壳布局契约（存在性 + 内容 AST）+ hello_aic 装配。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import check_shell_content, check_shell_layout
from apps.hello_aic.shell import build_shell

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    if cond:
        PASS.append(name)
        print(f"  \\u2705 {name}")
    else:
        FAIL.append(name)
        print(f"  \\u274c {name}")


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_dir = os.path.join(root, "apps", "hello_aic")
    for chk, label in ((check_shell_layout, "壳布局存在性"),
                       (check_shell_content, "壳内容 AST")):
        try:
            chk(app_dir)
            check(f"hello_aic {label} 通过", True)
        except RuntimeError as e:
            check(f"hello_aic {label} 通过", False)
            print(f"    {e}")
    try:
        s = build_shell()
        check("hello_aic 装配通过", len(getattr(s, "_mounts", [])) >= 1)
    except Exception as e:
        check("hello_aic 装配通过", False)
        print(f"    {e}")
    print(f"模板自检: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
'''


def _public_plugins(graph: dict) -> dict[str, dict]:
    """公共插件 = PUBLIC 标记（上浮过）。"""
    return {cls: info for cls, info in graph["plugins"].items()
            if info.get("public")}


def _unmarked_shared(graph: dict) -> list[str]:
    """未上浮但被多应用挂载的插件（提示用, 不自动上浮）。"""
    return sorted(cls for cls, info in graph["plugins"].items()
                  if not info.get("public") and len(info["apps"]) > 1)


def _copy_tree(src: str, dst: str) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git"))


def _plugin_pkg_copy(root: str, graph: dict, out_dir: str) -> list[str]:
    """复制公共插件包到模板（保持相对位置）, 返回已复制包路径列表。"""
    copied: list[str] = []
    for cls, info in _public_plugins(graph).items():
        pkg = _pkg_dir(root, info["module"])
        rel = os.path.relpath(pkg, root)
        dst = os.path.join(out_dir, rel)
        if dst in copied:
            continue
        if os.path.exists(dst):
            continue
        _copy_tree(pkg, dst)
        copied.append(dst)
    return copied


def _mount_line(cls: str, info: dict) -> str:
    """生成 profile 挂载行（特殊构造: ConfigPlugin 传路径, JobsPlugin 传 app_pkg）。"""
    if cls == "ConfigPlugin":
        return ('    ConfigPlugin(path=__file__.replace("profile.py", '
                '"config/config.local.ini")),')
    if cls == "JobsPlugin":
        return '    JobsPlugin(app_pkg="hello_aic"),   # 任务名协议（机制强制）'
    return f"    {cls}(),"


def _write_hello_aic(out_dir: str, graph: dict) -> None:
    """生成示例应用 hello_aic: init 壳骨架 + profile 挂载全部公共插件。"""
    from tools.init import (APP_CONFIG, APP_MAIN, APP_SHELL, APP_TASKS,
                            APP_WORKER)
    name = "hello_aic"
    ctx = {"name": name, "Name": "HelloAic"}
    app_dir = os.path.join(out_dir, "apps", name)
    os.makedirs(app_dir, exist_ok=True)
    with open(os.path.join(app_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(f'"""apps/{name} — {name} 示例应用。"""\n')
    for fname, tpl in (("main.py", APP_MAIN), ("shell.py", APP_SHELL),
                       ("tasks.py", APP_TASKS), ("worker.py", APP_WORKER)):
        with open(os.path.join(app_dir, fname), "w", encoding="utf-8") as f:
            f.write(tpl.format(**ctx))
    cfg = os.path.join(app_dir, "config")
    os.makedirs(cfg, exist_ok=True)
    with open(os.path.join(cfg, "config.local.ini"), "w", encoding="utf-8") as f:
        f.write(APP_CONFIG)

    # profile: 挂载全部公共插件（按包分组 import）
    publics = sorted(_public_plugins(graph).items(), key=lambda kv: kv[1]["module"])
    by_pkg: dict[str, list[str]] = {}
    for cls, info in publics:
        # 包前缀 = 插件类所在包目录（已复制到 out_dir）相对根转 module
        pkg = os.path.relpath(_pkg_dir(out_dir, info["module"]), out_dir
                              ).replace(os.sep, ".")
        by_pkg.setdefault(pkg, []).append(cls)

    lines = [f'"""apps/{name}/profile.py — 示例应用: 挂载模板全部公共插件。"""']
    for pkg in sorted(by_pkg):
        classes = ", ".join(sorted(by_pkg[pkg]))
        lines.append(f"from {pkg} import {classes}")
    lines.append("")
    lines.append("PLUGINS = [")
    for cls, info in publics:
        lines.append(_mount_line(cls, info))
    lines.append("]")
    with open(os.path.join(app_dir, "profile.py"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _verify(out_dir: str) -> list[str]:
    """模板验证: hello_aic 壳契约 + 装配。"""
    from kernel import check_shell_content, check_shell_layout
    problems: list[str] = []
    app_dir = os.path.join(out_dir, "apps", "hello_aic")
    for check in (check_shell_layout, check_shell_content):
        try:
            check(app_dir)
        except RuntimeError as e:
            problems.append(str(e))
    try:
        r = subprocess.run(
            [sys.executable, "-c",
             "from apps.hello_aic.shell import build_shell; "
             "s = build_shell(); print('hello_aic 装配通过')"],
            cwd=out_dir, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            problems.append(f"hello_aic 装配失败: {r.stderr.strip()[-300:]}")
    except Exception as e:
        problems.append(f"hello_aic 装配异常: {e}")
    return problems


def build_template(root: str, graph: dict, out_dir: str,
                   dry: bool, src_app: str | None) -> dict:
    """模板提取。dry=True 只返回报告。"""
    publics = _public_plugins(graph)
    unmarked = _unmarked_shared(graph)
    report = {
        "publics": sorted(publics),
        "unmarked_shared": unmarked,
        "out": out_dir,
        "src_app": src_app,
    }
    if dry:
        return report

    os.makedirs(out_dir, exist_ok=True)
    # ① 基础层
    for d in _BASE_DIRS:
        _copy_tree(os.path.join(root, d), os.path.join(out_dir, d))
    # ② 模板自检脚本（壳契约 + hello_aic 装配, 与模板自洽）
    os.makedirs(os.path.join(out_dir, "test"), exist_ok=True)
    with open(os.path.join(out_dir, "test", "template_check.py"),
              "w", encoding="utf-8") as f:
        f.write(_TEMPLATE_CHECK)
    # ③ 公共插件包
    report["pkgs"] = _plugin_pkg_copy(root, graph, out_dir)
    # ④ docs/learn
    _copy_tree(os.path.join(root, _DOCS_LEARN), os.path.join(out_dir, _DOCS_LEARN))
    # ⑤ 示例壳 hello_aic
    _write_hello_aic(out_dir, graph)
    # ⑥ requirements 自动生成（按模板实际 import 过滤）
    _generate_requirements(out_dir, os.path.join(root, "requirements.txt"))
    return report


def _render(report: dict, dry: bool) -> str:
    lines: list[str] = []
    lines.append(f"== 新应用开发模板提取（源参考: {report['src_app'] or '全部'}）==")
    lines.append(f"  公共插件（PUBLIC 标记, 进模板）: {report['publics'] or '无'}")
    if dry:
        lines.append(f"  输出: {report['out']}")
        if report["unmarked_shared"]:
            lines.append(f"  ⚠️ 未上浮但多应用挂载（不带走）: {report['unmarked_shared']}")
            lines.append("     如需保留: 先 aic promote XxxPlugin --yes")
        lines.append("")
        lines.append("（预演: 未提取, 确认后去掉 --dry-run 执行）")
    else:
        lines.append(f"  已复制插件包: {len(report.get('pkgs', []))} 个")
        lines.append(f"  模板已生成: {report['out']}")
        lines.append("    基础 AIC（kernel/tools/m0 回归/requirements）")
        lines.append("    + 公共插件 + 示例壳 apps/hello_aic + docs/learn")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="aic template",
        description="新应用开发模板提取: 只带走公共插件（PUBLIC 标记, 先 promote 再提取）。"
                    " 模板 = 基础 AIC + 公共插件 + 示例壳 hello_aic + docs/learn。")
    p.add_argument("app", nargs="?", default=None,
                   help="源应用名（参考; 公共插件来自全项目）")
    p.add_argument("--out", default="aic-template", help="模板输出目录")
    p.add_argument("--dry-run", action="store_true",
                   help="预演: 只显示清单, 不实际提取")
    args = p.parse_args(argv)

    root = _root()
    graph = build_graph()
    report = build_template(root, graph, os.path.abspath(args.out),
                            dry=args.dry_run, src_app=args.app)
    print(_render(report, dry=args.dry_run))
    if args.dry_run:
        return
    problems = _verify(os.path.abspath(args.out))
    if problems:
        print("\n⚠️ 模板验证未通过:")
        for msg in problems:
            print(f"  {msg}")
        raise SystemExit(1)
    print("\n✅ 模板验证通过（hello_aic 壳契约 + 装配）。"
          "\n   使用: cd 模板目录 → python -m uvicorn apps.hello_aic.main:app"
          "\n         → aic init my-app 加新应用")


if __name__ == "__main__":
    main()
