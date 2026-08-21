"""mvp_app/profile.py — MVP 插件组合（应用壳的组装点）。

应用 = 平台 + 插件组合。加不同业务插件 = 不同应用。
引擎选择是部署决策（挂载引擎插件 provides "agentLoop" 即覆盖壳默认 FakeLoop）。
"""
from __future__ import annotations

import os

from aic.extensions.platform.agent import TasksPlugin
from aic.extensions.platform.base import CachePlugin, ConfigPlugin, JobsPlugin, StoragePlugin, TelemetryPlugin
from aic.extensions.platform.base.jobs import CeleryJobQueue, FailoverJobQueue, ThreadJobQueue
from aic.extensions.platform.render import RenderPlugin
from aic.extensions.platform.security.sandbox import SandboxPlugin
from aic.extensions.platform.session import SessionPlugin
from aic.extensions.platform.stream import StreamPlugin
from extensions.business.writer import WriterPlugin

# 任务队列: Celery 主（broker 可用时）→ 线程池降级（Redis 未启动/故障时）
_BROKER = os.environ.get("KIT_BROKER_URL", "redis://127.0.0.1:6379/1")

PLUGINS = [
    # ── 基础设施（kit/base）──
    ConfigPlugin(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config",
                                   f"config.{os.environ.get('APP_ENV', 'local')}.ini")),
    TelemetryPlugin(),
    StoragePlugin(),
    CachePlugin(),
    JobsPlugin(impl=FailoverJobQueue(
        primary=CeleryJobQueue(broker_url=_BROKER),
        fallback=ThreadJobQueue(max_workers=4),
    ), app_pkg="mvp"),   # 任务名协议（机制强制）: 注册名须与 worker 侧同名
    # ── 平台能力 ──
    SandboxPlugin(),
    SessionPlugin(),
    RenderPlugin(),
    StreamPlugin(redis_url=_BROKER),   # SSE 进度推送（Redis 跨进程 / in-process 兜底）
    TasksPlugin(),              # 任务注册表（聚合键: 业务插件登记而非覆盖）
    # ── 业务 ──
    WriterPlugin(),          # inject sessions/renderers/tasks → boot 自动排序
]
