"""extensions/business/standard/tool.py — 本地规范库检索工具（领域共享）。

向本地检索 API 发 HTTP 查询，返回规范/标准条目（替代联网搜索）。
review 与 writer 共享（原项目 standard 领域子插件）。
"""
from __future__ import annotations

import json
import logging
import os
from urllib.request import ProxyHandler, Request, build_opener

logger = logging.getLogger(__name__)


class StandardSearchTool:
    """standard_search 工具：本地规范库检索。"""

    name = "standard_search"
    toolset = "standard_search"
    schema = {
        "name": "standard_search",
        "description": (
            "在本地标准/规范知识库中检索编辑依据等引用条目。"
            "支持按规范编号、关键词检索条文内容和适用范围。"
            "每次调用可传入多个关键词并行检索，返回各关键词的匹配条目。"
            "适用于子代理检查方案中的编制依据和条文引用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "检索关键词列表，可混合使用规范编号和内容关键词，"
                        '如 ["GB 50016", "防火间距", "耐火等级"]'
                    ),
                },
            },
            "required": ["keywords"],
        },
    }

    def __init__(self, search_url: str = "", timeout: float = 5.0,
                 max_bytes: int = 2 * 1024 * 1024):
        self._search_url = search_url or os.environ.get(
            "STANDARD_SEARCH_URL", "http://127.0.0.1:18765/v1/search")
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = build_opener(ProxyHandler({}))

    def handle(self, args: dict, **kw) -> str:
        keywords = args.get("keywords")
        if not keywords or not isinstance(keywords, list):
            return json.dumps({"error": "keywords 必须是非空的字符串列表"}, ensure_ascii=False)
        keywords = [str(k).strip() for k in keywords if k]
        if not keywords:
            return json.dumps({"error": "keywords 不能为空"}, ensure_ascii=False)

        try:
            body = json.dumps({"keywords": keywords}).encode("utf-8")
            req = Request(
                self._search_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self._opener.open(req, timeout=self._timeout) as resp:
                raw = resp.read(self._max_bytes)
                result = raw.decode("utf-8", errors="replace")
                logger.info(f"standard_search: status={resp.status} len={len(raw)} keywords={keywords}")
                return result
        except Exception as e:
            logger.warning(f"standard_search 请求失败: {e}")
            return json.dumps({"error": f"standard_search failed: {e}"}, ensure_ascii=False)


def _register() -> None:
    try:
        from tools.registry import registry
        tool = StandardSearchTool()
        registry.register(
            name=tool.name,
            toolset=tool.toolset,
            schema=tool.schema,
            handler=tool.handle,
            check_fn=None,
            description="在本地标准/规范知识库中检索条目",
            emoji="📚",
        )
    except ImportError:
        logger.debug("[review] tools.registry 未安装（非 hermes 环境），跳过 standard_search 注册")


_register()
