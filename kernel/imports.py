"""kernel/imports.py — 旁路 import 契约（机制强制）。

"黑箱之间藏了多少未知依赖"是接手恐惧的核心。组合结构已机制化
（inject 声明 / graph / blast_radius / 装配期校验）, 唯一的结构缺口是
**旁路 import**: 业务代码绕过 ctx 直接 import 其他扩展的实现/组件
（如 `from extensions.platform.base.storage import LocalStorage`）——
机制看不见、graph 看不见, 换实现时它还继续生效, 契约被悄悄绕过。

规则（三类合法跨盒 import, 其余一律违规）:

```
① 组合面   apps 可 import 扩展的适配器类（*Plugin 结尾）与引擎（loops 包）
② 组合点   profile.py 内实现选择自由（impl 构造注入 = 文档化换法）
③ 声明工具 无状态纯函数公共 API —— UTILITY_MODULES 白名单（新增 = 改常量 + 文档）
```

违规四型（报错文案带原因, 可行动）:
- 应用壳直连扩展实现 → 应走 ctx 服务
- 跨应用 import（apps.A → apps.B）→ 应用之间不得互相依赖
- 跨扩展根包旁路 → 应走 ctx 服务或声明公共工具
- 扩展反向 import 应用壳 → 依赖方向倒置

边界（文档化）: review 业务线整体排除扫描（不进发布包）; extensions→tools
不在检查范围（CLI 层附属, sandbox 补丁设计上反向）。

违规 → 装配时报错（RuntimeError, [kernel] 前缀, 收集式, sorted 确定性）——
与 M5 挂载校验 / 壳布局检查同款"大声失败"。
"""
from __future__ import annotations

import ast
import os

# 声明工具白名单: 无状态纯函数公共 API, 可跨盒 import。
# 新增工具 = 改这里 + 同步 SDK 文档（声明强制显式, 不允许静默旁路）。
#   extensions.platform.extract            → extract_document / ALLOWED_TYPES 等
#   extensions.platform.session.artifacts  → save/list/read/next_draft_version
UTILITY_MODULES = (
    "extensions.platform.extract",
    "extensions.platform.session.artifacts",
)

# 排除扫描的业务线（不进发布包, 卫生问题随业务线处理, 与 pyproject exclude 一致）
_EXCLUDED_DIRS = ("apps/review", "extensions/business/review")


def _own_root(rel: str) -> str | None:
    """文件所属根包（apps.<app> / extensions.<根>）; 无法判定返回 None。

    例子: apps/todo/main.py → apps.todo; extensions/business/todo/plugin.py
    → extensions.business.todo; extensions/platform/base/storage.py
    → extensions.platform.base（base 独立成根, 与 platform 其他包互不旁路）。
    """
    parts = rel.replace(os.sep, "/").split("/")
    if len(parts) >= 2 and parts[0] in ("apps", "extensions") and parts[1]:
        root = f"{parts[0]}.{parts[1]}"
        if parts[0] == "extensions" and len(parts) >= 3 and parts[2]:
            root += f".{parts[2]}"
        return root
    return None


def _relative_target(root: str, level: int, module: str | None) -> str:
    """相对导入解析为目标模块名。

    `from ..loops import X`（level=2）在 extensions.platform.base 里
    → extensions.platform.loops。level 超深 → 空串（逃出仓库, 放行）。
    """
    parts = root.split(".")
    cut = max(0, len(parts) - (level - 1))
    base = ".".join(parts[:cut])
    return f"{base}.{module}" if module and base else (base or "")


def _is_composition_surface(target: str, names: list[str]) -> bool:
    """组合面: loops 包（引擎组合）或 *Plugin 结尾的适配器类。"""
    if target.endswith(".loops") or ".loops." in target:
        return True
    return any(n.endswith("Plugin") for n in names)


def _is_utility(target: str) -> bool:
    """声明工具白名单（前缀匹配模块段, 含其子模块）。"""
    return any(target == u or target.startswith(u + ".") for u in UTILITY_MODULES)


def _reason(target: str, root: str) -> str:
    if target.startswith("apps."):
        if root.startswith("apps."):
            return "跨应用 import（应用之间不得互相依赖）"
        return "扩展反向 import 应用壳（依赖方向倒置）"
    if root.startswith("apps."):
        return ("应用壳直连扩展实现（应走 ctx 服务; 只允许组合面: "
                "*Plugin 结尾 / loops 包 / profile.py 组合点）")
    return "跨扩展根包旁路（应走 ctx 服务, 或声明公共工具: UTILITY_MODULES）"


def _scan_file(path: str, rel: str) -> list[str]:
    """AST 扫描单文件, 返回旁路违规清单（确定性: 按节点出现顺序）。"""
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError) as e:
        return [f"{rel} 无法解析: {e}"]

    root = _own_root(rel)
    if root is None:
        return []
    is_app = root.startswith("apps.")
    is_profile = os.path.basename(path) == "profile.py"

    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [(alias.name, []) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            target = (_relative_target(root, node.level, node.module)
                      if node.level else node.module or "")
            targets = [(target, [a.name for a in node.names])]
        else:
            continue

        for target, names in targets:
            # kernel / 标准库 / 第三方（非 apps./extensions. 前缀）→ 放行
            if not target or target == "kernel" or target.startswith("kernel."):
                continue
            if not (target.startswith("apps.") or target.startswith("extensions.")):
                continue
            # 自己根包内互 import → 放行
            if target == root or target.startswith(root + "."):
                continue
            # 组合点（profile.py）: 实现选择自由
            if is_profile:
                continue
            # 声明工具白名单: 无状态纯函数公共 API, 任意层可 import
            if _is_utility(target):
                continue
            # apps 文件: 组合面（*Plugin 结尾 / loops 包）
            if is_app and _is_composition_surface(target, names):
                continue
            problems.append(
                f"{rel}:{node.lineno} import {target}（{_reason(target, root)}）")

    return problems


def check_bypass_imports(project_root: str | os.PathLike) -> None:
    """旁路 import 契约: 扫描 apps/ 与 extensions/ 下的跨盒 import。

    违规抛 RuntimeError（收集式, 全部问题一次列出, sorted 确定性）;
    通过静默返回。目录缺失（apps/ 或 extensions/ 不存在）→ 跳过该半区。
    """
    project_root = os.path.abspath(project_root)
    problems: list[str] = []
    for base in ("apps", "extensions"):
        base_dir = os.path.join(project_root, base)
        if not os.path.isdir(base_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(base_dir):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for f in sorted(filenames):
                if not f.endswith(".py"):
                    continue
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, project_root).replace(os.sep, "/")
                if any(rel == e or rel.startswith(e + "/") for e in _EXCLUDED_DIRS):
                    continue
                problems.extend(_scan_file(full, rel))

    if problems:
        raise RuntimeError(
            "[kernel] 旁路 import 违规: " + "; ".join(sorted(problems)))
