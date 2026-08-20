"""kit/base/config.py — 配置基础设施插件（M4b）。

ctx.config: 分层配置读取（INI, 默认值兜底）。对应 app/base/config/ 的插件化。
"""
from __future__ import annotations

import configparser

from aic.kernel import Context, Plugin


class ConfigService:
    """配置服务（ctx.config）。"""

    def __init__(self, path: str | None = None):
        self._parser = configparser.ConfigParser()
        if path:
            self._parser.read(path, encoding="utf-8")

    def get(self, section: str, key: str, default: str = "") -> str:
        return self._parser.get(section, key, fallback=default)

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        return self._parser.getint(section, key, fallback=default)

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        return self._parser.getboolean(section, key, fallback=default)


class ConfigPlugin(Plugin):
    """配置插件：提供 ctx.config。可带路径参数（应用壳传 config.ini 路径）。"""

    provides = ["config"]

    def __init__(self, path: str | None = None):
        self._path = path

    def apply(self, ctx: Context):
        ctx.register("config", ConfigService(self._path))
