"""apps/file_convert/profile.py — 插件组合（tools.init 生成）。

应用壳的组装点: 平台插件 + 你的业务插件。
"""
from extensions.platform.base import CachePlugin, ConfigPlugin, JobsPlugin, StoragePlugin, TelemetryPlugin
from extensions.platform.render import RenderPlugin
from extensions.platform.security import SandboxPlugin
from extensions.platform.session import SessionPlugin
from extensions.platform.stream import StreamPlugin
from extensions.business.file_convert import FileConvertPlugin

PLUGINS = [
    # ── 基础设施 ──
    ConfigPlugin(path=__file__.replace("profile.py", "config/config.local.ini")),
    TelemetryPlugin(),
    StoragePlugin(),
    CachePlugin(),
    JobsPlugin(app_pkg="file_convert"),   # 任务名协议（机制强制）: 注册名须与 worker 侧同名
    # ── 平台能力 ──
    SandboxPlugin(),
    SessionPlugin(),
    RenderPlugin(),
    StreamPlugin(),
    # ── 业务（③ 声明: 挂载你的业务插件）──
    FileConvertPlugin(),
]
