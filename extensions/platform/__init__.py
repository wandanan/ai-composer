"""platform — L2 平台插件层（通用能力, 所有应用共享）。

- base/     基础设施插件: config/telemetry/storage/cache/jobs
- loops/    引擎插件: FakeLoop/HermesLoop/FailoverLoop
- security/ 沙箱插件（可逆补丁）
- session/  会话服务 + 产物管理
- render/   渲染注册表
- stream/   SSE 进度推送
"""
