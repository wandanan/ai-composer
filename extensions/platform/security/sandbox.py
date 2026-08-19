"""kit/security/sandbox.py — 工作区沙箱插件（M1c）。

把 Hermes 文件操作限制在已注册工作区内，且作为**可逆插件**：
- apply:   注册 ctx.sandbox 服务 + 安装边界补丁（保存原函数引用）
- unmount: 效果桶还原补丁（恢复原函数），零残留

泛化来源: `app/core/hack_hermes/re_resolve_path_for_task.py`
新增能力: 可逆性（原实现只 apply 不还原）；工作区经 ctx.sandbox 服务设置
          （替代业务层直接调 set_workspace）。

补丁范围（与源实现一致）:
- tools.file_tools._resolve_path_for_task   → 所有文件工具（read/write/patch）路径边界
- tools.file_operations.ShellFileOperations.search → search_files 越界搜索拦截

相对路径: 保持 Hermes 原始行为（绑定 TERMINAL_CWD / live tracking cwd 解析）。
绝对路径: 归一化后检查是否在工作区子树内，越界抛 PermissionError（工具层转 tool_error 返回给 LLM）。
并发安全: contextvars.ContextVar 存储工作区，线程隔离，子代理线程自动继承。
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable

from kernel import Context, Plugin

logger = logging.getLogger(__name__)

# 工作区 ContextVar：线程隔离，子代理线程自动继承（源实现同款机制）
_workspace_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "kit_sandbox_workspace", default=""
)


# ── 文件权限保护（上浮自 review security/fs.py: 通用, 任何 agent 工作区共用）──

def lock_dir_readonly(path: str) -> None:
    """递归移除目录树的写入权限, agent 只能读取不可修改。"""
    if not os.path.isdir(path):
        return
    try:
        for root, dirs, files in os.walk(path):
            for name in files:
                fp = os.path.join(root, name)
                mode = os.stat(fp).st_mode
                os.chmod(fp, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            for name in dirs:
                dp = os.path.join(root, name)
                mode = os.stat(dp).st_mode
                os.chmod(dp, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        mode = os.stat(path).st_mode
        os.chmod(path, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    except Exception as e:
        logger.warning(f"[sandbox] 只读锁定失败 {path}: {e}")


def unlock_dir(path: str) -> None:
    """递归恢复目录树的写入权限（与 lock_dir_readonly 相反）。"""
    if not os.path.isdir(path):
        return
    try:
        for root, dirs, files in os.walk(path):
            for name in files:
                fp = os.path.join(root, name)
                mode = os.stat(fp).st_mode
                os.chmod(fp, mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
            for name in dirs:
                dp = os.path.join(root, name)
                mode = os.stat(dp).st_mode
                os.chmod(dp, mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    except Exception as e:
        logger.warning(f"[sandbox] 解锁写入失败 {path}: {e}")


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """净化文件名, 防路径遍历和非法字符。"""
    filename = filename.replace("\x00", "")
    filename = filename.replace("/", "_").replace("\\", "_")
    filename = re.sub(r'[<>"|?*]', "_", filename)
    filename = filename.strip().strip(".")
    if len(filename) > max_length:
        name, _, ext = filename.rpartition(".")
        if ext and len(ext) <= 10:
            filename = name[: max_length - len(ext) - 1] + "." + ext
        else:
            filename = filename[:max_length]
    if not filename:
        filename = "unnamed"
    return filename


class SandboxService:
    """工作区沙箱服务（ctx.sandbox）。

    业务/会话层在创建会话工作区后调用 set_workspace() 注册边界；
    当前线程（及派生子代理线程）的所有文件操作以此路径为边界。
    """

    def set_workspace(self, native_workspace: str) -> None:
        """注册当前上下文的工作区边界（Windows 原生格式或任意可解析路径）。"""
        normalized = os.path.normpath(os.path.abspath(native_workspace))
        _workspace_ctx.set(normalized)
        logger.debug("[sandbox] 设置工作区 → %s", normalized)

    def get_workspace(self) -> str:
        """读取当前工作区；未注册时回退 TERMINAL_CWD（兼容旧路径）。"""
        ws = _workspace_ctx.get("")
        if ws:
            return ws
        return os.environ.get("TERMINAL_CWD", "")

    def clear_workspace(self) -> None:
        _workspace_ctx.set("")

    # ── 文件权限保护（上浮自 review）──

    def lock_dir_readonly(self, path: str) -> None:
        lock_dir_readonly(path)

    def unlock_dir(self, path: str) -> None:
        unlock_dir(path)

    def sanitize_filename(self, filename: str, max_length: int = 200) -> str:
        return sanitize_filename(filename, max_length)


# ── 路径归一化（Windows 原生 + bash 格式统一）──────────────────────

def _normalize_for_boundary(path: str) -> str:
    """归一化路径用于边界比较：bash 格式 (/d/...) → Windows 原生格式。"""
    if os.name == "nt" and path:
        m = re.match(r"^/([a-zA-Z])/(.*)", path)
        if m:
            path = f"{m.group(1).upper()}:\\{m.group(2).replace('/', '\\')}"
    return os.path.normpath(os.path.abspath(path))


def _check_boundary(filepath: str, workspace: str, hint: str) -> Path:
    """解析 filepath（含相对路径展开），越界抛 PermissionError，合法返回 Path。"""
    # bash 格式绝对路径先转 Windows 原生（否则 Path.is_absolute() 误判）
    if os.name == "nt":
        m = re.match(r"^/([a-zA-Z])/(.*)", filepath)
        if m:
            filepath = f"{m.group(1).upper()}:\\{m.group(2).replace('/', '\\')}"

    p = Path(filepath).expanduser()
    if not p.is_absolute():
        base = None
        try:
            from tools.file_tools import _get_live_tracking_cwd
            base = _get_live_tracking_cwd("default")
        except ImportError:
            pass
        base = base or os.environ.get("TERMINAL_CWD", os.getcwd())
        p = Path(base) / p

    if workspace:
        p_norm = Path(_normalize_for_boundary(str(p)))
        ws_norm = Path(_normalize_for_boundary(workspace))
        try:
            p_norm.relative_to(ws_norm)
        except ValueError:
            raise PermissionError(
                f"工作区边界限制: 禁止访问工作区外的路径。\n"
                f"  请求路径: {filepath}\n"
                f"  解析后路径: {p_norm}\n"
                f"  当前工作区: {ws_norm}\n"
                f"  提示: 只能访问工作区内的文件。"
            )

    return p.resolve()


# ── 补丁实现（工作区取自 SandboxService 的 ContextVar）─────────────

def _sandboxed_resolve_path(filepath: str, task_id: str = "default") -> Path:
    """带工作区边界检查的路径解析（替换 tools.file_tools._resolve_path_for_task）。"""
    workspace = _get_workspace()
    return _check_boundary(filepath, workspace, hint="file")


def _sandboxed_search(self, pattern: str, path: str = ".", target: str = "content",
                      file_glob: str = None, limit: int = 50, offset: int = 0,
                      output_mode: str = "content", context: int = 0, **kw: Any):
    """带工作区边界检查的 search_files（替换 ShellFileOperations.search）。"""
    workspace = _get_workspace()
    if workspace and path:
        search_path = os.path.expanduser(path)
        if os.name == "nt":
            m = re.match(r"^/([a-zA-Z])/(.*)", search_path)
            if m:
                search_path = f"{m.group(1).upper()}:\\{m.group(2).replace('/', '\\')}"
        p = Path(search_path)
        if not p.is_absolute():
            p = Path(workspace) / p
        p_norm = Path(_normalize_for_boundary(str(p)))
        ws_norm = Path(_normalize_for_boundary(workspace))
        try:
            p_norm.relative_to(ws_norm)
        except ValueError:
            raise PermissionError(
                f"工作区边界限制: 禁止在工作区外搜索。\n"
                f"  请求路径: {path}\n"
                f"  当前工作区: {ws_norm}"
            )
    return _ORIGINAL_SEARCH_REF[0](
        self, pattern=pattern, path=path, target=target,
        file_glob=file_glob, limit=limit, offset=offset,
        output_mode=output_mode, context=context, **kw,
    )


# search 补丁闭包引用原函数（模块级, 每次安装时更新）
_ORIGINAL_SEARCH_REF: list[Callable] = [None]


def _get_workspace() -> str:
    """工作区读取：优先 SandboxService 的 ContextVar，回退 TERMINAL_CWD。"""
    ws = _workspace_ctx.get("")
    if ws:
        return ws
    return os.environ.get("TERMINAL_CWD", "")


def _install_patches() -> list[Callable[[], None]]:
    """安装补丁，返回还原函数列表（进插件效果桶 → unmount 自动还原）。"""
    restore: list[Callable[[], None]] = []

    try:
        import tools.file_tools as ft
    except ImportError:
        ft = None
        logger.warning("[sandbox] tools.file_tools 不可用，跳过文件路径补丁")
    if ft is not None and hasattr(ft, "_resolve_path_for_task"):
        original = ft._resolve_path_for_task
        ft._resolve_path_for_task = _sandboxed_resolve_path
        restore.append(lambda: setattr(ft, "_resolve_path_for_task", original))
        logger.info("[sandbox] 已安装 _resolve_path_for_task 边界补丁")

    try:
        import tools.file_operations as fo
    except ImportError:
        fo = None
        logger.warning("[sandbox] tools.file_operations 不可用，跳过 search 补丁")
    if fo is not None and hasattr(fo.ShellFileOperations, "search"):
        original_search = fo.ShellFileOperations.search
        _ORIGINAL_SEARCH_REF[0] = original_search
        fo.ShellFileOperations.search = _sandboxed_search
        restore.append(lambda: setattr(fo.ShellFileOperations, "search", original_search))
        logger.info("[sandbox] 已安装 ShellFileOperations.search 边界补丁")

    return restore


class SandboxPlugin(Plugin):
    """工作区沙箱插件：提供 ctx.sandbox 服务 + 可逆安装文件边界补丁。"""

    provides = ["sandbox"]

    def apply(self, ctx: Context):
        ctx.register("sandbox", SandboxService())
        for restore in _install_patches():
            ctx.effect(restore)  # 进插件效果桶 → unmount 自动还原
