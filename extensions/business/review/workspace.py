"""review/workspace.py — 审查会话工作区创建（从 hermes.py setup_session_workspace 移植）。

工作区结构:
  {runtime}/{session_id}/materials/    待审查材料（只读）
                        /knowledge/    知识库 symlink（standards/historical_reviews, 只读）
                        /reports/      最终报告（可写）
                        /process_file_temp/ 草稿（可写）
                        /skill_resources/   Skill 资源（只读）
"""
from __future__ import annotations

import logging
import os

from extensions.business.review.knowledge import get_knowledge_base_dir
from extensions.business.review.paths import bash_path, find_bash

logger = logging.getLogger(__name__)


def _populate_skill_resources(ctx, session_dir: str, skill_id: str) -> None:
    """从 DB skill.resource（MinIO zip 路径）经平台 storage 下载解压, 排除 SKILL.MD。"""
    try:
        import io
        import shutil
        import tempfile
        import zipfile

        from extensions.business.review.data import ReviewSkill

        with ctx.get("db").session() as s:
            row = s.query(ReviewSkill).filter(ReviewSkill.skill_id == skill_id).first()
        if not row or not row.resource:
            return
        skill_name = row.name or skill_id

        storage = ctx.get("storage")
        raw = storage.get(row.resource)  # storage 协议 get(key) -> bytes
        if not raw:
            return

        tmp_root = tempfile.mkdtemp(prefix="skill_res_")
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                zf.extractall(tmp_root)
            tmp_dir = tmp_root
            entries = os.listdir(tmp_root)
            if len(entries) == 1 and os.path.isdir(os.path.join(tmp_root, entries[0])):
                tmp_dir = os.path.join(tmp_root, entries[0])

            dst_dir = os.path.join(session_dir, "skill_resources", skill_name)
            os.makedirs(dst_dir, exist_ok=True)
            for root, dirs, files in os.walk(tmp_dir):
                rel_dir = os.path.relpath(root, tmp_dir)
                target_dir = dst_dir if rel_dir == "." else os.path.join(dst_dir, rel_dir)
                os.makedirs(target_dir, exist_ok=True)
                for f in files:
                    if f.upper() == "SKILL.MD":
                        continue
                    dst = os.path.join(target_dir, f)
                    if not os.path.exists(dst):
                        shutil.copy2(os.path.join(root, f), dst)
            logger.info(f"[review] skill 资源已填充: {skill_id} → {dst_dir}")
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)
    except Exception as e:
        logger.warning(f"[review] skill resource 填充失败 {skill_id}: {e}")


def _symlink_knowledge(knowledge_dir: str, subdir: str) -> None:
    """知识库只读链接（不可用时写入路径引用文件 + 建空目录）。"""
    src = os.path.join(get_knowledge_base_dir(), "knowledge", subdir)
    dst = os.path.join(knowledge_dir, subdir)
    if os.path.exists(dst) or os.path.islink(dst):
        return
    if os.path.isdir(src):
        try:
            os.symlink(src, dst, target_is_directory=True)
            logger.info(f"[review] 知识库只读链接: {src} → {dst}")
        except OSError as e:
            ref = os.path.join(knowledge_dir, f"_{subdir}_path.txt")
            with open(ref, "w", encoding="utf-8") as f:
                f.write(src)
            os.makedirs(dst, exist_ok=True)
            logger.warning(f"[review] symlink 不可用 (err={e}), 路径已写入: {ref}")
    else:
        logger.warning(f"[review] 知识库源目录不存在: {src}")


def setup_session_workspace(ctx, session_id: str, skill_id: str = "",
                            knowledge_scope: list[str] | None = None) -> str:
    """创建会话隔离工作区并注册沙箱边界。返回 session_dir。"""
    runtime_dir = os.environ.get("WORKSPACE_RUNTIME_DIR") or os.path.abspath("./workspace-runtime")
    session_dir = os.path.join(runtime_dir, session_id)

    for sub in ("materials", "process_file_temp", "reports",
                "skill_resources", "knowledge"):
        os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

    # 权限: 仅 reports/ 与 process_file_temp/ 可写, 其余只读
    sandbox = ctx.get("sandbox")   # 平台文件权限保护
    for d in (os.path.join(session_dir, "materials"),
              os.path.join(session_dir, "skill_resources"),
              os.path.join(session_dir, "knowledge"), session_dir):
        sandbox.lock_dir_readonly(d)

    # 知识库 symlink
    knowledge_dir = os.path.join(session_dir, "knowledge")
    _symlink_knowledge(knowledge_dir, "standards")
    _symlink_knowledge(knowledge_dir, "historical_reviews")

    # Skill 资源（临时解锁写入后再锁回）
    if skill_id:
        sk_dir = os.path.join(session_dir, "skill_resources")
        sandbox.unlock_dir(sk_dir)
        _populate_skill_resources(ctx, session_dir, skill_id)
        sandbox.lock_dir_readonly(sk_dir)

    # bash 路径 + TERMINAL_CWD（引擎 shell 工具）
    bash = find_bash()
    if bash:
        os.environ["HERMES_GIT_BASH_PATH"] = bash
    os.environ["TERMINAL_CWD"] = bash_path(session_dir)

    # 沙箱注册（平台 SandboxPlugin 提供, 线程隔离）
    if ctx.has("sandbox"):
        ctx.get("sandbox").set_workspace(session_dir)

    logger.info(f"[review] session 工作目录: {session_dir}")
    return session_dir
