"""tools/skills.py — 开发 Skill 更新命令（aic skills, 同步）。

安装 ai-composer 新版本后, 用本命令把新版 aic-paradigm skill 覆盖到
项目根三平台（.claude/.codex/.agent）——AI 开发约束随框架版本演进。

与 init 的幂等复制不同: skills 是**覆盖更新**（旧版本被替换）;
只带 aic-paradigm, 内部发布流程 aic-release 不随项目分发。
"""
from __future__ import annotations

import os
import shutil
import sys


def skills(root: str | None = None) -> int:
    """覆盖更新项目根三平台 aic-paradigm skill（源 = aic 包内 assets）。"""
    root = os.path.abspath(root or os.environ.get("KIT_PROJECT_ROOT") or os.getcwd())
    from aic.tools.init import _copy_skills
    _copy_skills(root, overwrite=True)
    print(f"✅ 开发 Skill 已更新（三平台 aic-paradigm, 覆盖旧版本）: {root}")
    return 0


def main(rest: list[str]) -> None:
    if rest and rest[0] in ("-h", "--help"):
        print("用法: aic skills\n\n"
              "覆盖更新项目根三平台 aic-paradigm 开发 Skill（安装新版本后同步）。")
        return
    raise SystemExit(skills())


if __name__ == "__main__":
    main(sys.argv[1:])
