"""kit/base/storage.py — 对象存储基础设施插件（M4b）。

ctx.storage: 对象存储协议（put/get/exists）。
- LocalStorage:  本地目录实现（验证/兜底）
- MemoryStorage: 内存实现（测试/替换验证）
- MinioStorage:  真实 MinIO 适配器（协议合规 stub, 真实连接在 strangler 阶段接入）
对应 app/base/minio/ 的插件化。
"""
from __future__ import annotations

import os
import re
import tempfile
from typing import Protocol, runtime_checkable

from aic.kernel import Context, Plugin


@runtime_checkable
class ObjectStorage(Protocol):
    """对象存储协议。"""

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


def _validate_key(key: str) -> None:
    """存储 key 契约: / 分层, 只允许 [a-zA-Z0-9._/-], 禁止 : \\ .. 绝对路径 空串。

    key 直接映射为文件路径（LocalStorage）——冒号在 Windows 是非法字符,
    .. 有路径穿越风险, 绝对路径会逃出存储根。违规抛 ValueError（运行期静默 OSError → 装配即报）。
    """
    if not isinstance(key, str) or not key:
        raise ValueError(f"[storage] 非法 key: {key!r}（不能为空）")
    if key.startswith("/") or re.match(r"^[A-Za-z]:", key):
        raise ValueError(f"[storage] 非法 key: {key!r}（禁止绝对路径）")
    if "\\" in key or ":" in key:
        raise ValueError(
            f"[storage] 非法 key: {key!r}（禁止 \\ 和 :, 用 / 分层, 如 'todo/abc/meta'）")
    parts = key.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"[storage] 非法 key: {key!r}（禁止空段 / ./ ..）")
    if not re.fullmatch(r"[a-zA-Z0-9._/-]+", key):
        raise ValueError(
            f"[storage] 非法 key: {key!r}（只允许字母数字 . _ - /）")


class LocalStorage:
    """本地目录对象存储。"""

    def __init__(self, root: str | None = None):
        # 默认 = 稳定共享目录（与 sessions 默认同构）: mkdtemp 每进程新目录
        # 会让 worker 进程读不到 API 进程写入的文件（跨进程静默断裂）
        self.root = root or os.path.join(tempfile.gettempdir(), "kit_storage")

    def put(self, key: str, data: bytes) -> None:
        _validate_key(key)
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def get(self, key: str) -> bytes:
        _validate_key(key)
        with open(os.path.join(self.root, key), "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        _validate_key(key)
        return os.path.exists(os.path.join(self.root, key))


class MemoryStorage:
    """内存对象存储（替换验证实现）。"""

    def __init__(self):
        self._data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        _validate_key(key)
        self._data[key] = data

    def get(self, key: str) -> bytes:
        _validate_key(key)
        return self._data[key]

    def exists(self, key: str) -> bool:
        _validate_key(key)
        return key in self._data


class MinioStorage:
    """MinIO 适配器（协议合规 stub：保存连接配置, 真实连接 strangler 阶段接入）。"""

    def __init__(self, endpoint: str = "", access_key: str = "",
                 secret_key: str = "", bucket: str = "kit"):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket

    def put(self, key: str, data: bytes) -> None:
        raise NotImplementedError("strangler 阶段接入真实 MinIO")

    def get(self, key: str) -> bytes:
        raise NotImplementedError("strangler 阶段接入真实 MinIO")

    def exists(self, key: str) -> bool:
        return False


class StoragePlugin(Plugin):
    """存储插件：提供 ctx.storage。可通过构造参数注入实现（默认 LocalStorage）。"""

    provides = ["storage"]

    def __init__(self, impl: ObjectStorage | None = None):
        self._impl = impl

    def apply(self, ctx: Context):
        ctx.register("storage", self._impl or LocalStorage())
