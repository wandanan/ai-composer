"""review/paths.py — 工作区路径工具（从审查应用 path_utils 移植, 去 logger 依赖）。

- resolve_workspace / workspace_parent: 工作目录解析
- find_bash / bash_path: bash 检测与 Windows↔bash 路径转换
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def workspace_parent(work_dir: str) -> str:
    """获取 work_dir 的父目录，处理根目录边界。"""
    parent = os.path.dirname(work_dir.rstrip('/\\'))
    if parent in ('/', '\\') or not parent:
        return work_dir.rstrip('/\\')
    return parent


def resolve_workspace(work_dir: str) -> str:
    """解析工作目录路径 — 支持绝对/相对路径，不存在则自动创建。"""
    if not work_dir:
        return os.getcwd()
    path = Path(work_dir)
    if path.is_absolute():
        resolved = str(path.resolve())
    else:
        resolved = str(Path(_PROJECT_ROOT).joinpath(path).resolve())
    if not os.path.isdir(resolved):
        os.makedirs(resolved, exist_ok=True)
    return resolved


_AVAILABLE_BASH: Optional[str] = None
_BASH_CHECKED = False


def find_bash() -> Optional[str]:
    """找到可用的 bash（Windows 优先 Git Bash, 其次 WSL; 其他平台 which bash）。"""
    global _AVAILABLE_BASH, _BASH_CHECKED
    if _BASH_CHECKED:
        return _AVAILABLE_BASH
    _BASH_CHECKED = True

    if os.name != "nt":
        _AVAILABLE_BASH = shutil.which("bash") or "/bin/bash"
        return _AVAILABLE_BASH

    candidates: list[str] = []
    for base in (
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "bin", "bash.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "git", "bin", "bash.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "git", "usr", "bin", "bash.exe"),
    ):
        if base and os.path.isfile(base):
            candidates.append(base)

    wsl = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "bash.exe")
    if os.path.isfile(wsl):
        candidates.append(wsl)

    for bash in candidates:
        try:
            result = subprocess.run(
                [bash, "-c", "echo ok"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            if result.returncode == 0 and "ok" in result.stdout:
                _AVAILABLE_BASH = bash
                return _AVAILABLE_BASH
        except Exception:
            continue

    _AVAILABLE_BASH = None
    return None


def bash_path(path: str) -> str:
    """Windows 路径 → bash 可识别格式（Git Bash /d/..., WSL /mnt/d/...）。"""
    if not path or os.name != "nt":
        return path
    m = re.match(r"^([A-Za-z]):[/\\]", path)
    if not m:
        return path
    drive = m.group(1).lower()
    rest = path[m.end():].replace("\\", "/")
    bash = (find_bash() or "").lower()
    if "system32" in bash and "git" not in bash:
        return f"/mnt/{drive}/{rest}"
    return f"/{drive}/{rest}"
