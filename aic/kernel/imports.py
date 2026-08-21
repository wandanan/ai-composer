"""aic.kernel.imports — 旁路 import 契约（机制强制）。

"黑箱之间藏了多少未知依赖"是接手恐惧的核心。组合结构已机制化
（inject 声明 / graph / blast_radius / 装配期校验）, 唯一的结构缺口是
**旁路 import**: 业务代码绕过 ctx 直接 import 其他扩展的实现/组件
（如 `from aic.extensions.platform.base.storage import LocalStorage`）——
机制看不见、graph 看不见, 换实现时它还继续生效, 契约被悄悄绕过。

域（0.2.0 命名空间重构后）:
- 用户空间（项目根平铺）: apps/（壳）、extensions/business/、extensions/platform/（项目平台）
- 框架空间（aic 包, 只读）: aic/kernel、aic/extensions/platform/、aic/apps/hello_aic
- 扫描三区: 根 apps/ + 根 extensions/ + aic/extensions/

规则（三类合法跨盒 import, 其余一律违规）:

```
① 组合面   壳可 import 扩展的适配器类（*Plugin 结尾）与引擎（loops 包）
② 组合点   profile.py 内实现选择自由（impl 构造注入 = 文档化换法）
③ 声明工具 无状态纯函数公共 API —— UTILITY_MODULES 白名单（新增 = 改常量 + 文档）
```

违规四型（报错文案带原因, 可行动）:
- 应用壳直连扩展实现 → 应走 ctx 服务
- 跨应用 import（apps.A → apps.B）→ 应用之间不得互相依赖
- 跨扩展根包旁路（业务↔平台, 用户空间↔框架空间）→ 应走 ctx 服务或声明公共工具
- 扩展反向 import 应用壳 → 依赖方向倒置

边界（文档化）: extensions→tools 不在检查范围（CLI 层附属, sandbox 补丁设计上反向;
hermes 环境提供顶层 tools）。业务豁免默认无（精确到文件, 见 _DEFAULT_EXCLUDED）。

违规 → 装配时报错（RuntimeError, [kernel] 前缀, 收集式, sorted 确定性）——
与 M5 挂载校验 / 壳布局检查同款"大声失败"。
"""
from __future__ import annotations

import ast
import os

# 声明工具白名单: 无状态纯函数公共 API, 可跨盒 import。
# 新增工具 = 改这里 + 同步 SDK 文档（声明强制显式, 不允许静默旁路）。
#   aic.extensions.platform.extract            → extract_document / ALLOWED_TYPES 等
#   aic.extensions.platform.session.artifacts  → save/list/read/next_draft_version
UTILITY_MODULES = (
    "aic.extensions.platform.extract",
    "aic.extensions.platform.session.artifacts",
    "aic.extensions.platform.security.sanitize",
)

# 项目级业务排除默认值（默认无豁免——整仓按契约扫描）。
# 业务插件若有遗留架构债需豁免: 精确到文件配置（非整条业务线）, 经
# check_bypass_imports(exclude=...) 或环境变量 KIT_EXCLUDED_DIRS 覆盖。
_DEFAULT_EXCLUDED: tuple[str, ...] = ()


def _resolve_exclude(exclude: tuple[str, ...] | None) -> tuple[str, ...]:
    if exclude is not None:
        return tuple(exclude)
    env = os.environ.get("KIT_EXCLUDED_DIRS", "")
    if env.strip():
        return tuple(e.strip() for e in env.split(",") if e.strip())
    return _DEFAULT_EXCLUDED


def _own_root(rel: str) -> str | None:
    """文件所属根包; 无法判定返回 None。

    用户空间: apps/todo/main.py → apps.todo; extensions/business/todo/plugin.py
    → extensions.business.todo; extensions/platform/base/storage.py
    → extensions.platform.base（项目平台, base 独立成根）。
    框架空间: aic/extensions/platform/base/cache.py → aic.extensions.platform.base;
    aic/apps/hello_aic/x.py → aic.apps.hello_aic。
    """
    parts = rel.replace(os.sep, "/").split("/")
    if parts and parts[0] == "aic":
        if len(parts) >= 3 and parts[1] in ("extensions", "apps"):
            if parts[1] == "extensions" and len(parts) >= 4 and parts[3]:
                return f"aic.extensions.{parts[2]}.{parts[3]}"
            if len(parts) >= 3 and parts[2]:
                return f"aic.{parts[1]}.{parts[2]}"
        return None
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


def _app_surface_ok(target: str, names: list[str]) -> bool:
    """应用壳组合面判定（按名字逐个, 非整条放行）。"""
    # loops 包: 引擎组合, 整体放行
    if target.endswith(".loops") or ".loops." in target:
        return True
    # 逐名: 全部 *Plugin 结尾才算组合面（ast.Import 的 names 为空 → 非组合面）
    return bool(names) and all(n.endswith("Plugin") for n in names)


def _is_utility(target: str) -> bool:
    """声明工具白名单（前缀匹配模块段, 含其子模块）。"""
    return any(target == u or target.startswith(u + ".") for u in UTILITY_MODULES)


def _reason(target: str, root: str) -> str:
    if target.startswith("apps."):
        if root.startswith(("apps.", "aic.apps.")):
            return "跨应用 import（应用之间不得互相依赖）"
        return "扩展反向 import 应用壳（依赖方向倒置）"
    if root.startswith(("apps.", "aic.apps.")):
        return ("应用壳直连扩展实现（应走 ctx 服务; 只允许组合面: "
                "*Plugin 结尾 / loops 包 / profile.py 组合点）")
    return "跨扩展根包旁路（应走 ctx 服务, 或声明公共工具: UTILITY_MODULES）"


def _type_checking_imports(tree: ast.AST) -> set[int]:
    """收集位于 `if TYPE_CHECKING:` 块内的 Import/ImportFrom 节点 id（类型标注用途, 运行时不存在）。"""
    ids: set[int] = set()

    def _is_tc_test(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id == "TYPE_CHECKING"
        if isinstance(node, ast.Attribute):
            return node.attr == "TYPE_CHECKING"
        return False

    def _walk(node: ast.AST, in_tc: bool) -> None:
        if isinstance(node, ast.If):
            tc = in_tc or _is_tc_test(node.test)
            for child in ast.iter_child_nodes(node):
                _walk(child, tc)
            return
        if in_tc and isinstance(node, (ast.Import, ast.ImportFrom)):
            ids.add(id(node))
        for child in ast.iter_child_nodes(node):
            _walk(child, in_tc)

    _walk(tree, False)
    return ids


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
    is_app = root.startswith(("apps.", "aic.apps."))
    is_profile = os.path.basename(path) == "profile.py"

    tc_imports = _type_checking_imports(tree)
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

        # TYPE_CHECKING 块内的 import 放行: 仅类型标注用途, 运行时不存在——
        # 业务插件靠它标注平台服务（如 ConfigService）, 属契约面而非旁路实现。
        if id(node) in tc_imports:
            continue

        for target, names in targets:
            # 标准库 / 第三方（非 apps./extensions./aic. 前缀）→ 放行
            if not target:
                continue
            if not (target.startswith("apps.") or target.startswith("extensions.")
                    or target.startswith("aic.")):
                continue
            # 框架内核与统一入口 → 任意层可 import
            if target == "aic" or target == "aic.kernel" \
                    or target.startswith("aic.kernel."):
                continue
            # 协议面: agent/loops 协议包（业务实现协议必须 import 形状——与实现解耦的契约面）
            if target.startswith(("aic.extensions.platform.agent",
                                  "aic.extensions.platform.loops")):
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
            # apps 文件: 组合面（loops 包整体放行; 逐名 *Plugin 类全合规才放行——
            # `from base.storage import LocalStorage, StoragePlugin` 里
            # LocalStorage 是旁路实现, 仍拦）
            if is_app and _app_surface_ok(target, names):
                continue
            problems.append(
                f"{rel}:{node.lineno} import {target}（{_reason(target, root)}）")

    return problems


def check_bypass_imports(project_root: str | os.PathLike,
                         exclude: tuple[str, ...] | None = None) -> None:
    """旁路 import 契约: 扫描 apps/ 与 extensions/ 下的跨盒 import。

    违规抛 RuntimeError（收集式, 全部问题一次列出, sorted 确定性）;
    通过静默返回。目录缺失（apps/ 或 extensions/ 不存在）→ 跳过该半区。
    exclude: 豁免相对路径（逗号分隔环境变量 KIT_EXCLUDED_DIRS 可覆盖默认）。
    """
    project_root = os.path.abspath(project_root)
    excluded = _resolve_exclude(exclude)
    problems: list[str] = []
    # 扫描四区: 根 apps/（壳）+ 根 extensions/（用户业务）+ aic/extensions/（框架平台）
    #          + aic/apps/（示例壳 hello_aic——之前漏检, 与根 apps 同契约）
    for base in ("apps", "extensions",
                 os.path.join("aic", "extensions"), os.path.join("aic", "apps")):
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
                if any(rel == e or rel.startswith(e + "/") for e in excluded):
                    continue
                problems.extend(_scan_file(full, rel))

    if problems:
        raise RuntimeError(
            "[kernel] 旁路 import 违规: " + "; ".join(sorted(problems)))
