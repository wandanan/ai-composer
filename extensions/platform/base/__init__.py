"""kit/base — 基础设施插件（M4b/M4c 验证）。

把配置/遥测/存储/缓存/任务队列做成与业务插件同构的插件：
- 同样具备 服务注册(ctx.*)/依赖注入(inject)/实现替换/可逆销毁
- 对应 app/base/ 的 strangler 映射：config→config, logger+tracing→telemetry,
  minio→storage, redis→cache, tasks→jobs
- 真实连接（MinIO/Redis/Celery）在 strangler 阶段接入, 本阶段为协议合规 stub + 本地实现
- 降级矩阵 = 同一协议多实现 + Failover 包装（jobs 已验证）
"""
from .cache import CachePlugin
from .config import ConfigPlugin
from .db import DbPlugin
from .jobs import JobsPlugin
from .storage import StoragePlugin
from .telemetry import TelemetryPlugin

__all__ = ["ConfigPlugin", "TelemetryPlugin", "StoragePlugin", "CachePlugin",
           "JobsPlugin", "DbPlugin"]
