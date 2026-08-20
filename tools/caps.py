"""tools/caps.py — 能力清单命令（aic caps, 查）。

给 AI/开发者看"框架现在有什么可用"——四问判断源全部落声明层, 不用读源码:
  语义（是不是这功能）  → 服务 key + 特性说明（docstring 首行）
  形状（代码能不能跑）  → 协议/服务形状（provides + 插件名）
  实现（内部件合不合适）→ 换法面（构造参数: impl/redis_url/runtime_dir...）
  行为（需要增强吗）    → 特性说明（插件写 docstring 时声明行为特性）

输出四段:
  平台服务   ctx.get(key) 直接消费（SDK §3 服务表的运行时投影）
  业务插件   extensions/business/*, profile.py 挂载
  声明工具   UTILITY_MODULES 白名单（纯函数 API, 可直接 import）
  引擎       agentLoop 实现选择（shell 引擎决策 + profile.py 可换）

逐模块 try/except: 坏模块跳过并提示, 不拖垮整个清单。
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
from typing import Any

from kernel import Plugin
from kernel.imports import UTILITY_MODULES

_SECTIONS = ("platform", "business")


def _iter_packages(root: str):
    """枚举 extensions/{platform,business}/* 的插件包（含 __init__.py 的目录）。"""
    for area in _SECTIONS:
        area_dir = os.path.join(root, "extensions", area)
        if not os.path.isdir(area_dir):
            continue
        for name in sorted(os.listdir(area_dir)):
            pkg = os.path.join(area_dir, name)
            if os.path.isdir(pkg) and os.path.isfile(os.path.join(pkg, "__init__.py")):
                yield f"extensions.{area}.{name}", pkg


def _load_module(module_name: str) -> tuple[Any | None, str | None]:
    """导入扩展包; 失败返回 (None, 原因)。"""
    try:
        return importlib.import_module(module_name), None
    except Exception as e:
        return None, f"{module_name} 不可导入: {e.__class__.__name__}: {e}"


def _doc_first_line(cls, mod) -> str:
    doc = (getattr(cls, "__doc__", None) or getattr(mod, "__doc__", "") or "").strip()
    return doc.splitlines()[0] if doc else ""


def _collect_plugins(mod) -> list[dict]:
    """收集模块内定义的 Plugin 子类（sorted, 确定性）。"""
    out = []
    for cls_name, cls in sorted(vars(mod).items()):
        if not isinstance(cls, type) or cls is Plugin or not issubclass(cls, Plugin):
            continue
        try:
            sig = str(inspect.signature(cls.__init__))[1:-1]
            core = sig[5:] if sig.startswith("self, ") else sig
            if core in ("/", "*args, **kwargs", ""):
                sig = ""
        except (TypeError, ValueError):
            sig = ""
        out.append({
            "cls": cls_name,
            "provides": list(getattr(cls, "provides", []) or []),
            "sig": sig,
            "doc": _doc_first_line(cls, mod),
        })
    return out


def _collect_engines(mod) -> list[str]:
    """收集 loops 包内的引擎选择（AgentLoop 协议实现 + 引擎插件）。"""
    from kernel.protocols import AgentLoop
    out = []
    for cls_name, cls in sorted(vars(mod).items()):
        if not isinstance(cls, type):
            continue
        try:
            ok = cls is not AgentLoop and issubclass(cls, AgentLoop)
        except TypeError:
            ok = False
        if ok:
            out.append(cls_name)
    return out


def _fmt_keyed(rows: list[tuple[str, str, str, str]]) -> list[str]:
    """平台服务: (key, cls, sig, doc) → 对齐行（消费方按 key 查）。"""
    if not rows:
        return []
    w = max(len(r[0]) for r in rows)
    lines = []
    for key, cls, sig, doc in rows:
        parts = [f"{key:<{w}}  {cls}"]
        if sig:
            parts.append(f"换法:({sig})")
        if doc:
            parts.append(f"特性: {doc}")
        lines.append("  " + "  ".join(parts))
    return lines


def _fmt_plugins(rows: list[tuple[str, list[str], str]]) -> list[str]:
    """业务插件: (cls, provides, doc) → 对齐行（挂载单元, 每插件一行）。"""
    if not rows:
        return []
    w = max(len(r[0]) for r in rows)
    lines = []
    for cls, provides, doc in rows:
        parts = [f"{cls:<{w}}"]
        if provides:
            parts.append(f"provides=[{', '.join(provides)}]")
        if doc:
            parts.append(f"特性: {doc}")
        lines.append("  " + "  ".join(parts))
    return lines


def caps(root: str | None = None) -> int:
    root = os.path.abspath(root or os.getcwd())
    ext_dir = os.path.join(root, "extensions")
    if not os.path.isdir(ext_dir):
        print(f"未找到 {ext_dir}（请在项目根目录运行 aic caps）")
        return 1

    platform_rows: list[tuple[str, str, str, str]] = []
    business_rows: list[tuple[str, list[str], str]] = []
    engines: list[str] = []

    for module_name, _pkg in _iter_packages(root):
        mod, err = _load_module(module_name)
        if err:
            print(f"⚠️ {err}")
            continue
        plugins = _collect_plugins(mod)
        if module_name.startswith("extensions.platform"):
            for info in plugins:
                for key in (info["provides"] or [info["cls"]]):
                    platform_rows.append((key, info["cls"], info["sig"], info["doc"]))
            if "extensions.platform.loops" in module_name:
                engines = _collect_engines(mod)
        else:
            for info in plugins:
                business_rows.append((info["cls"], info["provides"], info["doc"]))

    print("== 平台服务（ctx.get(key) 消费, 见 SDK §3）==")
    print("\n".join(_fmt_keyed(platform_rows)) or "  （无）")
    print("\n== 业务插件（profile.py 挂载）==")
    print("\n".join(_fmt_plugins(business_rows)) or "  （无）")
    print("\n== 声明工具（纯函数 API, 可直接 import）==")
    for u in UTILITY_MODULES:
        print(f"  {u}")
    print("\n== 引擎（agentLoop 实现选择）==")
    print(f"  {' / '.join(engines) if engines else '（无）'}")
    return 0


def main(rest: list[str]) -> None:
    if rest and rest[0] in ("-h", "--help"):
        print("用法: aic caps\n\n显示框架可用能力: 平台服务 / 业务插件 / 声明工具 / 引擎。")
        return
    raise SystemExit(caps())


if __name__ == "__main__":
    main(sys.argv[1:])
