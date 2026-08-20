"""extensions/platform/loops/hermes/ — Hermes 引擎适配器（真实引擎插件）。

不进发布包（pyproject 排除）: 平台不绑定任何真实引擎。要用真实引擎时,
把它作为普通插件挂到应用 profile.py 的 PLUGINS（提供 "agentLoop" 即覆盖 fake）。

实现 AgentLoop 协议，包装 run_agent.AIAgent。

引擎职责边界（与业务解耦的关键）：
- 引擎是"哑的"：系统提示词 / 工具集由调用方（任务）通过 kw 传入，引擎不组装业务 prompt
- hermes 内部事件（thinking/stream/tool）→ 翻译成平台事件广播（ctx.emit），
  供任何插件监听（SSE 推送 / 日志 / 统计），引擎自身不关心消费方
- 每轮新建 AIAgent + finally close（沿用"实例间无共享状态"设计）
- 引擎内部才 import run_agent —— 消费方永远看不到 hermes
"""
from __future__ import annotations

from typing import Any

from aic.kernel import Context, Plugin


class HermesLoop:
    """Hermes 引擎适配器：实现 AgentLoop 协议。"""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        provider: str = "",
        ctx: Context | None = None,
    ):
        self.name = "hermes"
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._provider = provider
        self.ctx = ctx
        self._patched = False

    def _apply_engine_patches(self) -> None:
        """通用引擎补丁（禁 lazy-install 装无用包, 上浮自 review re_check_toolset）。

        幂等: 只 patch 一次。所有用 hermes 引擎的应用都受益, 非业务专属。
        """
        if self._patched:
            return
        import os
        os.environ.setdefault("HERMES_DISABLE_LAZY_INSTALLS", "1")
        try:
            import run_agent
            if getattr(run_agent, "check_toolset_requirements", None) is not None:
                run_agent.check_toolset_requirements = lambda: {}
                self._patched = True
        except ImportError:
            pass

    def run_conversation(
        self,
        user_message: str,
        conversation_history: list | None = None,
        **kw: Any,
    ) -> dict:
        self._apply_engine_patches()           # 通用引擎补丁（禁 lazy-install）
        from run_agent import AIAgent  # 引擎内部才 import hermes

        ctx = self.ctx

        def _emit(event: str, payload: dict) -> None:
            if ctx is not None:
                ctx.emit(event, payload)

        agent = AIAgent(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            provider=self._provider or None,
            session_id=None,
            session_db=None,
            ephemeral_system_prompt=kw.get("system_prompt", ""),
            enabled_toolsets=kw.get("toolsets") or [],
            quiet_mode=False,
            skip_memory=True,
            skip_context_files=True,
            # ── hermes 内部事件 → 平台事件广播 ──
            thinking_callback=lambda text: _emit("agent/thinking", {"content": text}),
            stream_delta_callback=lambda delta, **_: _emit("llm/stream", {"delta": delta}),
            tool_start_callback=lambda cid, name, args, **_: _emit(
                "tools/pre-execute", {"call_id": cid, "name": name, "args": args}),
            tool_complete_callback=lambda cid, name, args, result, **_: _emit(
                "tools/post-execute",
                {"call_id": cid, "name": name, "result": str(result)[:200]}),
            # 子代理/工具进度（审查场景 SSE: subagent_start/tool_started 等）
            tool_progress_callback=lambda event_type, **kw: _emit(
                "agent/tool_progress", {"event": event_type, **kw}),
        )
        try:
            return agent.run_conversation(
                user_message, conversation_history=conversation_history or [])
        finally:
            agent.close()

    def close(self) -> None:
        pass


class HermesEnginePlugin(Plugin):
    """Hermes 引擎插件：声明提供 ctx.agentLoop 能力。

    声明三层：
    - inject = ["config"]   → 装配时保证 config 先就绪（LLM 配置来源）
    - provides = ["agentLoop"] → boot 拓扑排序索引
    - ctx.register(...)     → 运行时登记（同 key 可被其他引擎覆盖）
    """

    inject = ["config"]
    provides = ["agentLoop"]

    def apply(self, ctx: Context):
        cfg = ctx.get("config")
        llm = cfg.get("llm", {})
        ctx.register("agentLoop", HermesLoop(
            ctx=ctx,
            model=llm.get("LLM_MODEL", ""),
            api_key=llm.get("LLM_API_KEY", ""),
            base_url=llm.get("LLM_BASE_URL", ""),
            provider=llm.get("LLM_PROVIDER", ""),
        ))
