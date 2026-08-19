"""mvp_app — 编写应用 MVP（FastAPI 可运行 + 全插件装配）。

应用 = 平台 + 插件组合的首次完整落地：
- 10 个插件一次装配（5 基础设施 + 沙箱/会话/渲染 + 引擎 + writer 业务）
- FastAPI 提供 HTTP 入口；任务经 ctx.jobs（Celery 主 / 线程池降级）异步执行
"""
