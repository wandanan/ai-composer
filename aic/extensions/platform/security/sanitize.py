"""aic.extensions.platform.security.sanitize — 文件名净化（声明工具, 无状态纯函数）。

独立成模块（而非与 SandboxService 同模块）: 消费方按"声明工具"白名单
import, 不把整个沙箱服务实现暴露为公共面（UTILITY_MODULES 豁免本模块）。
"""
from __future__ import annotations

import re


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


__all__ = ["sanitize_filename"]
