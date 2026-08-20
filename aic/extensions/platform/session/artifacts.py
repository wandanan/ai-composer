"""kit/session/artifacts.py — 产物管理（平台通用，M2）。

产物 = 会话工作区中的文件，按 kind 分目录、版本化：

    {session_dir}/
    ├── summary.md               # kind=summary
    ├── outline.md               # kind=outline
    ├── chapters/01_xx.md        # kind=chapters
    ├── merged/draft_v1.md       # kind=merged（版本化）
    └── output/方案_v1.md        # kind=output（版本化）

业务插件约定自己的产物命名；本模块只提供通用落盘/读取/列表/版本递增。
"""
from __future__ import annotations

import os


def artifact_path(session_dir: str, kind: str, name: str) -> str:
    """产物绝对路径（kind 即子目录名）。"""
    return os.path.join(session_dir, kind, name)


def save_artifact(session_dir: str, kind: str, name: str, content: str) -> str:
    """落盘产物，返回路径。"""
    path = artifact_path(session_dir, kind, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def read_artifact(session_dir: str, kind: str, name: str) -> str:
    """读取产物文本。"""
    with open(artifact_path(session_dir, kind, name), encoding="utf-8") as f:
        return f.read()


def list_artifacts(session_dir: str, kind: str) -> list[str]:
    """列出某类产物文件名（排序）。"""
    d = os.path.join(session_dir, kind)
    if not os.path.isdir(d):
        return []
    return sorted(os.listdir(d))


def next_draft_version(session_dir: str, kind: str, prefix: str,
                       suffix: str = ".md") -> int:
    """下一个版本号 = 现有版本数 + 1（版本只增不删，历史保留）。

    0.2.1: kind/prefix 必填（业务侧显式传——平台不默认任何业务产物命名惯例）。
    """
    return len([n for n in list_artifacts(session_dir, kind)
                if n.startswith(prefix) and n.endswith(suffix)]) + 1
