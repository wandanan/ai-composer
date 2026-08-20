"""extensions/platform/loops/openai/ — OpenAI 兼容引擎适配器（发布包内置真引擎）。

实现 AgentLoop 协议（aic.extensions.platform.loops.AgentLoop）:
  run_conversation(user_message, conversation_history=None, **kw) -> dict
    - system_prompt / toolsets 走 **kw（协议约定: 引擎是"哑的", 不组装业务 prompt）
    - session_id 走 **kw: 流式 delta 事件 payload 携带它（事件契约: 须带 session_id）
  流式: stream=True 逐片解析, 每片 emit "llm/stream" 事件（delta 字段, 与 hermes 事件名一致）

兼容任何 OpenAI Chat Completions 兼容 API（OpenAI / DeepSeek / 通义 / Kimi ...）。
纯标准库实现（urllib）——延续内核零第三方依赖。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from aic.kernel import Context, Plugin


class OpenAILoop:
    """OpenAI 兼容引擎适配器（AgentLoop 协议, 消费方只依赖协议形状）。"""

    name = "openai"

    def __init__(self, *, model: str, api_key: str, base_url: str,
                 provider: str = "", ctx: Context | None = None):
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._provider = provider
        self.ctx = ctx

    def run_conversation(
        self,
        user_message: str,
        conversation_history: list | None = None,
        **kw: Any,
    ) -> dict:
        """执行一轮对话, 返回 {final_response, messages, token_usage}。

        角色提示词走 kw["system_prompt"]; 流式 delta 事件带 kw["session_id"]。
        """
        system_prompt = kw.get("system_prompt", "")
        session_id = kw.get("session_id", "")

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(conversation_history or [])
        messages.append({"role": "user", "content": user_message})

        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps({
                "model": self._model,
                "messages": messages,
                "stream": True,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._api_key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                text = self._drain_stream(resp, session_id)
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"[openai] 引擎调用失败 HTTP {e.code}: "
                f"{e.read().decode('utf-8', 'replace')[:200]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"[openai] 引擎调用失败（网络/配置错误）: {e.reason}") from e

        return {
            "final_response": text,
            "messages": messages + [{"role": "assistant", "content": text}],
            "token_usage": {"input_tokens": 0, "output_tokens": len(text)},
        }

    def _drain_stream(self, resp, session_id: str) -> str:
        """逐行解析 SSE（data: {...}）, 每片 delta 广播 llm/stream 事件。"""
        parts: list[str] = []
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {}).get("content")
                if delta:
                    parts.append(delta)
                    if self.ctx is not None:
                        self.ctx.emit("llm/stream",
                                      {"session_id": session_id, "delta": delta})
        return "".join(parts)

    def close(self) -> None:
        pass


class OpenAIEnginePlugin(Plugin):
    """OpenAI 兼容引擎插件: 提供 ctx.agentLoop（发布包内置真引擎, 部署决策）。

    inject = ["config"] → 装配时保证 config 先就绪（LLM 配置来源, 与 hermes 同构）。
    挂载即覆盖壳默认的 FakeLoop。
    """

    inject = ["config"]
    provides = ["agentLoop"]

    def apply(self, ctx: Context):
        cfg = ctx.get("config")
        llm = cfg.get("llm", {})
        ctx.register("agentLoop", OpenAILoop(
            ctx=ctx,
            model=llm.get("LLM_MODEL", ""),
            api_key=llm.get("LLM_API_KEY", ""),
            base_url=llm.get("LLM_BASE_URL", ""),
            provider=llm.get("LLM_PROVIDER", ""),
        ))
