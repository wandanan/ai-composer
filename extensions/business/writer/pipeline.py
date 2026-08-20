"""biz/writer/pipeline.py — 编写流水线（M2：5 阶段 + 修订闭环）。

阶段编排放业务层（pipeline 状态机）；平台只提供引擎/会话/产物机制。
每阶段经 ctx.emit("pipeline/phase") 广播进度，每章经 chapter/status 透出。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from aic.kernel import Context, ServiceNotFound
from aic.kernel.protocols import Phase
from aic.extensions.platform.session.artifacts import (
    list_artifacts,
    next_draft_version,
    read_artifact,
    save_artifact,
)
from extensions.business.writer.task import WriterTask

CHAPTER_CONCURRENCY = 3  # 分章并行度


class WriterPipeline:
    """5 阶段编写流水线: understand → outline → write(并行) → merge → render。

    消费纪律: 每次调用时 ctx.get('agentLoop')，不缓存引用 —— 引擎可任意替换。
    """

    PHASES = ("understand", "outline", "write", "merge", "render")

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self._phase_stats: dict[str, float] = {}

    # ── 内部工具 ──

    def _loop(self):
        return self.ctx.get("agentLoop")  # 调用时取（消费纪律）

    def _prompt_ctx(self):
        task = self.ctx.get("tasks")[WriterTask.id]
        return (task.build_system_prompt(self.ctx), task.toolsets(Phase.FIRST))

    def _phase(self, session, name: str) -> None:
        self._phase_stats[name] = time.time()   # 可观测性: 阶段耗时统计
        self.ctx.emit("pipeline/phase", {"phase": name,
                                         "session_id": session.session_id})

    def _compute_durations(self) -> dict:
        """各阶段耗时（秒）：相邻阶段起点差，末段到当前时间。"""
        names = list(self._phase_stats)
        if not names:
            return {}
        durations = {}
        for i, name in enumerate(names):
            end = self._phase_stats[names[i + 1]] if i + 1 < len(names) else time.time()
            durations[name] = round(end - self._phase_stats[name], 2)
        return durations

    # ── 主流程 ──

    def run(self, session, project_info: str, chapters: list[str]) -> dict:
        """执行完整 5 阶段流水线，产物落盘到 session.dir，返回本轮摘要。"""
        loop, (sp, ts) = self._loop(), self._prompt_ctx()
        sdir = session.dir

        # Phase 1 需求理解
        self._phase(session, "understand")
        summary = loop.run_conversation(
            f"请总结以下项目的施工概况: {project_info}",
            system_prompt=sp, toolsets=ts,
        )["final_response"]
        save_artifact(sdir, "summary", "summary.md", summary)

        # Phase 2 大纲生成
        self._phase(session, "outline")
        outline = loop.run_conversation(
            f"请为以下项目生成施工方案大纲, 包含章节: {', '.join(chapters)}\n项目概况: {project_info}",
            system_prompt=sp, toolsets=ts,
        )["final_response"]
        save_artifact(sdir, "outline", "outline.md", outline)

        # Phase 3 分章并行编写
        self._phase(session, "write")

        def _write_chapter(idx: int, name: str) -> str:
            content = loop.run_conversation(
                f"请编写第{idx + 1}章: {name}",
                system_prompt=sp, toolsets=ts,
            )["final_response"]
            save_artifact(sdir, "chapters", f"{idx + 1:02d}_{name}.md", content)
            self.ctx.emit("chapter/status", {"chapter": name, "status": "done",
                                             "session_id": session.session_id})
            return name

        with ThreadPoolExecutor(max_workers=min(CHAPTER_CONCURRENCY, len(chapters))) as ex:
            list(ex.map(lambda item: _write_chapter(*item), enumerate(chapters)))

        # Phase 4 合并 + 一致性校验
        self._phase(session, "merge")
        version = next_draft_version(sdir)
        merged = self._merge(loop, sdir, sp, ts)
        save_artifact(sdir, "merged", f"draft_v{version}.md", merged)

        # Phase 5 渲染（md 兜底 + 平台渲染注册表: docx 交付件）
        self._phase(session, "render")
        outputs = self._render(session, outline, merged, version)

        self.ctx.emit("pipeline/done", {"session_id": session.session_id,
                                        "version": version})

        return {
            "version": version,
            "chapters": len(chapters),
            "loop_name": getattr(loop, "name", "?"),
            "outputs": outputs,
            "stats": self._compute_durations(),
        }

    def _render(self, session, outline: str, merged: str, version: int) -> dict:
        """渲染: md 兜底（可读/回放）+ 渲染注册表（docx 交付件, 若有注册）。"""
        sdir = session.dir
        md_name = f"方案_v{version}.md"
        save_artifact(sdir, "output", md_name, f"{outline}\n\n{merged}")

        docx_name = None
        try:
            renderers = self.ctx.get("renderers")
        except ServiceNotFound:
            renderers = None
        if renderers is not None and renderers.has("docx"):
            docx_name = renderers.get("docx").render(
                session, merged=merged, outline=outline, version=version)
        return {"md": md_name, "docx": docx_name}

    def _merge(self, loop, sdir: str, sp: str, ts: list) -> str:
        parts = []
        for name in list_artifacts(sdir, "chapters"):
            parts.append(f"# {name}\n{read_artifact(sdir, 'chapters', name)}")
        body = "\n\n".join(parts)
        return loop.run_conversation(
            f"请将以下章节合并为完整施工方案文档, 并做一致性校验（术语/编号/交叉引用）:\n\n{body}",
            system_prompt=sp, toolsets=ts,
        )["final_response"]

    # ── 修订闭环 ──

    def revise(self, session, feedback: str, chapter_file: str) -> dict:
        """评审反馈修订: 定位章节 → 重写 → 重合并 → 重渲染 (version+1)。

        chapter_file: 章节文件名（如 03_施工部署.md），定位由反馈内容决定。
        """
        loop, (sp, ts) = self._loop(), self._prompt_ctx()
        sdir = session.dir

        content = loop.run_conversation(
            f"请根据以下评审反馈重写章节 {chapter_file}:\n{feedback}",
            system_prompt=sp, toolsets=ts,
        )["final_response"]
        save_artifact(sdir, "chapters", chapter_file, content)
        self.ctx.emit("chapter/status", {"chapter": chapter_file, "status": "revised",
                                         "session_id": session.session_id})

        version = next_draft_version(sdir)
        merged = self._merge(loop, sdir, sp, ts)
        save_artifact(sdir, "merged", f"draft_v{version}.md", merged)

        outline = read_artifact(sdir, "outline", "outline.md")
        outputs = self._render(session, outline, merged, version)

        self.ctx.emit("pipeline/done", {"session_id": session.session_id,
                                        "version": version})

        return {
            "version": version,
            "chapter": chapter_file,
            "loop_name": getattr(loop, "name", "?"),
            "outputs": outputs,
        }
