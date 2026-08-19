"""review/security — 审查安全域（提示词规则 / 引擎补丁）。

文件权限保护（lock/unlock/sanitize）已上浮到平台 ctx.sandbox（SandboxService）。
对外统一:
  from extensions.business.review.security import (
      PromptGuard, ToolPolicy,     # 提示词规则（审查专属）
      install_patches,             # hermes 引擎补丁（delegate/ensure 审查专属）
  )
"""
from extensions.business.review.security.hermes_patches import install_patches
from extensions.business.review.security.prompt import PromptGuard, ToolPolicy

__all__ = ["PromptGuard", "ToolPolicy", "install_patches"]
