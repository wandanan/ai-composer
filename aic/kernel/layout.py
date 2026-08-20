"""kernel/layout.py — 壳布局契约（机制强制）。

壳约束的本质是"能力必须落在可复用层（插件）, 壳只放一次性组装代码"。
约束分两类, 各自打靶:

```
① 存在性检查（客观完备）:
   装配组（必须齐全）:  __init__.py / profile.py / shell.py / tasks.py / worker.py
   入口组（至少一个）:  main.py(HTTP) / cli.py(CLI) —— 新形态建议登记（约定）
   config/             必须为目录（shell.py 的 load_config 硬编码读它）
② 内容检查（AST, 打本质）:
   壳内自定义 .py（非装配组/入口组/test_*）不得:
   a. import extensions.*            → 直接拿实现, 违反消费纪律（get 不 import）
   b. 定义 Plugin 子类               → 壳不提供能力（能力在插件）
   c. 调用 .register/.emit/.effect   → 提供/接线动作属插件 apply
      （消费动作 .get 放行——端点本来就要 get 能力）
```

**插件区是隐式概念**：除地基（kernel/apps/tools）外的一切目录都是插件可待之地,
boot 装配不看路径。extensions/ 只是 init 模板与推荐目录（惯例, 非强制）——
开发者删掉自建目录, 不拦着。

违规 → 装配时报错（RuntimeError, [kernel] 前缀, 收集式, 确定性输出）——
与 M5 挂载校验（kernel.py 的 mount）同款"大声失败"。
依据: docs/design/organization-contract.md。
"""
from __future__ import annotations

import ast
import os

# 装配组: 框架规定每个应用壳必须齐全的文件（tools/init 全量生成,
# tasks/worker 为"空档位": 可以不用但必须要有）
ASSEMBLY_FILES = ("__init__.py", "profile.py", "shell.py", "tasks.py", "worker.py")

# 入口组: 框架已知的入口形态（至少一个）。新增形态 = 建议登记
# （organization-contract.md 登记表 + init 模板）, 但不禁止自命名——部署
# 命令（uvicorn apps.x.main:app）按实际文件名走。
ENTRY_FILES = ("main.py", "cli.py")

# 内容检查: 壳内自定义 .py 禁止的接线动作（提供/广播/效果——属插件 apply）
_FORBIDDEN_CALLS = ("register", "emit", "effect")


def check_shell_layout(app_dir: str | os.PathLike) -> None:
    """存在性检查（客观完备项）。违规抛 RuntimeError, 通过静默返回。

    校验项（收集式, 全部检查后一次性报错）:
      ① 装配组必须齐全
      ② 入口组至少一个
      ③ config 存在则必须为目录（shell.py 的 load_config 硬编码读它）
    自定义文件/目录不检查存在性——内容由 check_shell_content 管。
    """
    if not os.path.isdir(app_dir):
        raise RuntimeError(f"[kernel] 应用壳目录不存在或不是目录: {app_dir}")

    entries = sorted(os.listdir(app_dir))
    files = {e for e in entries if os.path.isfile(os.path.join(app_dir, e))}

    problems: list[str] = []

    # ① 装配组必须齐全（"可以不用但必须要有": tasks/worker 空档位也算齐全）
    missing = [f for f in ASSEMBLY_FILES if f not in files]
    if missing:
        problems.append(f"缺少装配文件: {missing}")

    # ② 入口组至少一个（HTTP 或 CLI, 或多形态并存）
    if not any(f in files for f in ENTRY_FILES):
        problems.append("缺少入口文件（main.py/cli.py 至少一个）")

    # ③ config 存在但为文件 → 违规（load_config 硬编码读 config/config.local.ini）
    if "config" in entries and not os.path.isdir(os.path.join(app_dir, "config")):
        problems.append("config 应为目录")

    if problems:
        raise RuntimeError(
            f"[kernel] 应用壳布局违规 {app_dir}: " + "; ".join(problems))


def _custom_py_files(app_dir: str):
    """枚举壳内自定义 .py（非装配组/入口组/test_*; 含子目录, 剪枝 __pycache__/config）。

    yield (绝对路径, 相对 app_dir 的路径)。
    """
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "config"))
        rel_root = os.path.relpath(root, app_dir)
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            if rel_root == "." and (f in ASSEMBLY_FILES or f in ENTRY_FILES
                                    or (f.startswith("test_") and f.endswith(".py"))):
                continue
            path = os.path.join(root, f)
            yield path, os.path.relpath(path, app_dir)


def _scan_ast(tree: ast.AST, rel: str) -> list[str]:
    """AST 扫描一个文件, 返回违规清单（确定性顺序: 按节点出现顺序）。"""
    problems: list[str] = []
    for node in ast.walk(tree):
        # a. import extensions.* / aic.extensions.* → 直接拿实现（profile.py 等装配组已豁免）
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_extension_import(alias.name):
                    problems.append(f"{rel} import 插件实现: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and _is_extension_import(node.module):
                problems.append(f"{rel} import 插件实现: {node.module}")
        # b. 定义 Plugin 子类 → 壳不提供能力
        elif isinstance(node, ast.ClassDef):
            if any(_is_plugin_base(b) for b in node.bases):
                problems.append(f"{rel} 定义插件类: {node.name}")
        # c. .register/.emit/.effect → 提供/接线动作属插件 apply（.get 消费放行）
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) \
                    and node.func.attr in _FORBIDDEN_CALLS:
                problems.append(f"{rel} 接线动作: .{node.func.attr}(")
    return problems


def _is_extension_import(name: str) -> bool:
    """扩展实现前缀判定（用户平铺 extensions.* 或框架 aic.extensions.*）。"""
    return name == "extensions" or name.startswith("extensions.") \
        or name == "aic.extensions" or name.startswith("aic.extensions.")


def _is_plugin_base(base: ast.expr) -> bool:
    """基类是否为 Plugin（名字末段为 Plugin, 如 Plugin / kernel.Plugin）。"""
    name = getattr(base, "id", None) or getattr(base, "attr", None)
    return isinstance(name, str) and name == "Plugin"


def check_shell_content(app_dir: str | os.PathLike) -> None:
    """内容检查（AST, 打本质）: 壳内自定义 .py 不得含业务代码/接线动作。

    违规抛 RuntimeError（收集式, 全部问题一次列出）。
    """
    if not os.path.isdir(app_dir):
        return  # 存在性检查已覆盖

    problems: list[str] = []
    for path, rel in _custom_py_files(app_dir):
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except (OSError, SyntaxError) as e:
            problems.append(f"{rel} 无法解析: {e}")
            continue
        problems.extend(_scan_ast(tree, rel))

    if problems:
        raise RuntimeError(
            f"[kernel] 应用壳内容违规 {app_dir}: " + "; ".join(problems))
