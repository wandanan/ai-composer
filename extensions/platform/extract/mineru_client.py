"""review/mineru_client.py — MinerU 文档解析引擎客户端（从原项目 mineru_extract 移植）。

批量提交 + 轮询 + MD5 缓存 + 进度估算。
可选引擎: ENGINE=mineru 时启用（需 MinerU API 服务）, 默认 local（pymupdf 文本）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_ESTIMATED_PARSE_SECONDS = 180   # 单文件解析估算时长（进度用）
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0


class MinerUClient:
    """MinerU 客户端: submit → poll → get_result。"""

    def __init__(self, base_url: str, api_key: str = "",
                 timeout: int = 3600, poll_interval: float = 3.0,
                 cache_enabled: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.cache_enabled = cache_enabled
        self._cache_dir = os.path.join(
            os.environ.get("TMPDIR", tempfile.gettempdir()), "mineru_cache")

    # ── 提交 ──

    def submit_task(self, pdf_bytes: bytes, filename: str) -> str:
        """提交解析任务, 返回 task_id。multipart 表单对齐原项目。"""
        boundary = "----kit-form-" + hashlib.md5(os.urandom(16)).hexdigest()
        form = [
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="return_md"\r\n\r\ntrue',
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="table_enable"\r\n\r\ntrue',
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="formula_enable"\r\n\r\ntrue',
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="parse_method"\r\n\r\nocr',
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="effort"\r\n\r\nmedium',
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="lang_list"\r\n\r\nch',
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="backend"\r\n\r\nhybrid-engine',
            b"--" + boundary.encode(),
            b'Content-Disposition: form-data; name="file"; filename="' +
            filename.encode() + b'"\r\nContent-Type: application/octet-stream\r\n\r\n',
            pdf_bytes,
            b"\r\n--" + boundary.encode() + b"--\r\n",
        ]
        body = b"\r\n".join(form)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/tasks", data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                tid = (data.get("task_id") or data.get("id")
                       or (data.get("data") or {}).get("task_id"))
                if not tid:
                    raise RuntimeError(f"MinerU 提交无 task_id: {data}")
                return str(tid)
            except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
                logger.warning(f"[review] MinerU 提交第 {attempt + 1} 次失败: {e}")
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (2 ** attempt))
        raise RuntimeError("MinerU 提交失败")

    # ── 轮询 ──

    def poll_status(self, task_id: str) -> dict:
        req = urllib.request.Request(f"{self.base_url}/tasks/{task_id}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        d = data.get("data", data)
        return {"task_id": task_id,
                "status": d.get("status") or d.get("state") or "pending",
                "queued_ahead": d.get("queued_ahead", 0),
                "started_at": d.get("started_at")}

    def get_result(self, task_id: str) -> str:
        """获取 md 结果（多级字段兼容）。"""
        req = urllib.request.Request(f"{self.base_url}/tasks/{task_id}/result")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = (data.get("results") or {}).get("0", {}) or {}
        for key in ("md_content", "md", "markdown", "content", "text"):
            if results.get(key):
                return results[key]
        for key in ("md_content", "md", "markdown", "content", "text"):
            if data.get(key):
                return data[key]
        nested = (data.get("data") or {}).get("result") or {}
        if isinstance(nested, str):
            return nested
        for key in ("md_content", "md", "markdown", "content", "text"):
            if nested.get(key):
                return nested[key]
        raise RuntimeError(f"MinerU 结果解析失败: {str(data)[:200]}")

    # ── 主入口（带 MD5 缓存 + 进度估算）──

    def extract(self, pdf_bytes: bytes, filename: str,
                progress_callback=None) -> str:
        """解析 PDF 为 Markdown（MD5 缓存命中直接读）。"""
        digest = hashlib.md5(pdf_bytes).hexdigest()
        if self.cache_enabled:
            cache_path = os.path.join(self._cache_dir, f"{digest}.md")
            if os.path.isfile(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    return f.read()

        task_id = self.submit_task(pdf_bytes, filename)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            st = self.poll_status(task_id)
            status = st["status"]
            if status in ("done", "success", "completed"):
                text = self.get_result(task_id)
                if self.cache_enabled and text:
                    os.makedirs(self._cache_dir, exist_ok=True)
                    with open(cache_path, "w", encoding="utf-8") as f:
                        f.write(text)
                return text
            if status in ("failed", "error", "canceled"):
                raise RuntimeError(f"MinerU 解析失败: {status}")
            # 进度估算: 10 ~ 85%
            if progress_callback:
                elapsed = st.get("started_at") and time.time() - st["started_at"] or 0
                pct = 10 + min(elapsed / _ESTIMATED_PARSE_SECONDS, 1) * 75
                try:
                    progress_callback({"stage": "parse", "progress": round(pct)})
                except Exception:
                    pass
            time.sleep(self.poll_interval)
        raise RuntimeError("MinerU 解析超时")
