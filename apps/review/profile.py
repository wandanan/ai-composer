"""apps/review/profile.py — 插件组合（应用壳组装点）。

平台插件（通用能力）+ review 业务插件。
审查用 DB 会话模型（自有）, 不挂 SessionPlugin/RenderPlugin。

并发: KIT_CACHE_URL 配置时 cache 用 RedisCache（多进程共享锁/running）,
      否则默认 MemoryCache（单进程验证）。
"""
import os

from aic.extensions.platform.base import (
    CachePlugin,
    ConfigPlugin,
    DbPlugin,
    JobsPlugin,
    StoragePlugin,
    TelemetryPlugin,
)
from aic.extensions.platform.security import SandboxPlugin
from aic.extensions.platform.stream import StreamPlugin
from aic.extensions.platform.extract import ExtractPlugin
from aic.extensions.platform.standard import StandardPlugin
from extensions.business.review import ReviewPlugin


def _cache_plugin():
    """cache 实现按环境切换: KIT_CACHE_URL → RedisCache（多进程共享）, 默认 MemoryCache。"""
    url = os.environ.get("KIT_CACHE_URL", "")
    if url:
        from aic.extensions.platform.base.cache import RedisCache
        return CachePlugin(impl=RedisCache(url=url))
    return CachePlugin()


PLUGINS = [
    # ── 基础设施 ──
    ConfigPlugin(path=__file__.replace("profile.py", "config/config.local.ini")),
    TelemetryPlugin(),
    StoragePlugin(),
    _cache_plugin(),
    JobsPlugin(app_pkg="review"),   # 任务名协议（机制强制）: 注册名须与 worker 侧同名
    DbPlugin(),
    # ── 平台能力 ──
    SandboxPlugin(),
    StreamPlugin(),
    ExtractPlugin(),
    # ── 业务 ──
    StandardPlugin(),   # 共享领域插件（规范检索, review/writer 共用）
    ReviewPlugin(),
]
