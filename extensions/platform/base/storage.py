"""kit/base/storage.py — 对象存储基础设施插件（M4b）。

ctx.storage: 对象存储协议（put/get/exists）。
- LocalStorage:  本地目录实现（验证/兜底）
- MemoryStorage: 内存实现（测试/替换验证）
- MinioStorage:  真实 MinIO 适配器（协议合规 stub, 真实连接在 strangler 阶段接入）
对应 app/base/minio/ 的插件化。
"""
from __future__ import annotations

import os
import tempfile
from typing import Protocol, runtime_checkable

from kernel import Context, Plugin


@runtime_checkable
class ObjectStorage(Protocol):
    """对象存储协议。"""

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    """本地目录对象存储。"""

    def __init__(self, root: str | None = None):
        self.root = root or tempfile.mkdtemp(prefix="kit_storage_")

    def put(self, key: str, data: bytes) -> None:
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def get(self, key: str) -> bytes:
        with open(os.path.join(self.root, key), "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return os.path.exists(os.path.join(self.root, key))


class MemoryStorage:
    """内存对象存储（替换验证实现）。"""

    def __init__(self):
        self._data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._data[key] = data

    def get(self, key: str) -> bytes:
        return self._data[key]

    def exists(self, key: str) -> bool:
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
