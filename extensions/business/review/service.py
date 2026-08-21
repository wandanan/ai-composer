"""review/service.py — 审查核心服务（ReviewService, 从 conversations.py 范式化移植）。

基础设施全部走平台协议（cache/stream/storage/jobs/agentLoop），
DB 会话/消息/文件模型在 models.py（SQLAlchemy）。
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime

from extensions.business.review.data import ReviewFile, ReviewMessage, ReviewSession
from extensions.business.review.knowledge import filter_knowledge
from extensions.business.review.report import _extract_report, _extract_title
from extensions.business.review.skill import load_skill
from extensions.business.review.workspace import setup_session_workspace

logger = logging.getLogger(__name__)

QUEUE_REVIEW = "review"
QUEUE_FOLLOWUP = "followup"

RUNNING_TTL = 7200          # running 标记 TTL（无心跳则自愈）
TURN_GUARD_TTL = 3600       # turn 幂等守卫 TTL（防重投递双跑）
SESSION_LOCK_TTL = 600      # 会话锁 TTL（原子 SET NX; 心跳续期）
TURN_STARTED_TTL = 86400    # turn:started 标记（硬超时判据）
MAX_ENGINE_RETRIES = 5      # 引擎调用退避重试上限
RETRY_BASE_DELAY = 1.0      # 退避基延迟（秒, 指数增长封顶 30s）

STALE_TIMEOUT = 600         # updated_at 陈旧判定（崩溃恢复）
TURN_HARD_TIMEOUT = 3600    # turn 硬超时（崩溃恢复）
STALE_TASK_MAX_AGE = 1800   # 任务排队超时丢弃
HEARTBEAT_INTERVAL = 15     # 心跳秒（续期 running/锁 + bump updated_at）
PROGRESS_LIMIT = 200        # review_progress 事件上限
# 落 review_progress 的事件（状态推导 + SQL 轮询降级素材; 不含 llm/stream 高频 delta）
_PROGRESS_EVENTS = {"session_created", "extracting", "queue_status", "thinking",
                    "action", "message", "report_ready", "done", "error",
                    "heartbeat", "tool_started", "subagent_start", "session_recovered"}

# 引擎事件 → 审查 SSE 事件名映射
_ENGINE_EVENT_MAP = {
    "agent/thinking": "thinking",
    "llm/stream": "message",
    "tools/pre-execute": "action",
    "tools/post-execute": "action",
    # 子代理/工具进度: 事件名动态（event_type.replace(".","_"), 对齐原项目）
    "agent/tool_progress": "tool_progress",
}


class ReviewService:
    """审查业务服务：会话创建 / 执行轮 / 追问轮 / 报告与状态查询。"""

    def __init__(self, ctx):
        self.ctx = ctx

    def _db_session(self):
        """with 上下文: 平台 db 会话（ctx.get("db"), 可替换实现 → 换库零改动）。"""
        from contextlib import contextmanager

        @contextmanager
        def _scope():
            s = self.ctx.get("db").session()
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        return _scope()

    # ── 平台能力（调用时取, 不缓存引用 → 可替换）──

    def _loop(self):
        return self.ctx.get("agentLoop")

    def _jobs(self):
        return self.ctx.get("jobs")

    def _stream(self):
        return self.ctx.get("stream")

    def _storage(self):
        return self.ctx.get("storage")

    def _cache(self):
        return self.ctx.get("cache")

    def _sse(self, session_id: str, event: str, data: dict) -> None:
        try:
            self._stream().publish(session_id, event, data)
        except Exception as e:
            logger.warning(f"SSE 推送失败 [{event}] session={session_id}: {e}")
        if event in _PROGRESS_EVENTS:
            self._append_progress(session_id, event, data)

    def _append_progress(self, session_id: str, event: str, data: dict) -> None:
        """落 review_progress（状态推导 + SQL 轮询降级素材, 原项目 review_progress 列）。"""
        try:
            with self._db_session() as s:
                sess = s.get(ReviewSession, session_id)
                if sess is None:
                    return
                prog = sess.get_progress()
                prog.append({"event": event, "ts": time.time(), **data})
                if len(prog) > PROGRESS_LIMIT:
                    del prog[:-PROGRESS_LIMIT]
                sess.review_progress = _jstr(prog)
        except Exception as e:
            logger.debug(f"[review] progress 落库失败: {e}")

    def _bump_updated_at(self, session_id: str) -> None:
        try:
            with self._db_session() as s:
                sess = s.get(ReviewSession, session_id)
                if sess:
                    sess.updated_at = datetime.now()
        except Exception:
            pass

    # ── 会话创建 ──

    def start_session(self, file_id_entries: list[dict], project_type: str,
                      skill_id: str, user_id: str = "", metadata: dict | None = None,
                      batch_id: str = "") -> dict:
        """创建审查会话：建 DB 行 + 检查提取状态 → 直投队列或返回 needs_extraction。"""
        metadata = metadata or {}
        session_id = uuid.uuid4().hex[:12]

        skill_text = load_skill(skill_id) if skill_id else ""
        knowledge_scope = filter_knowledge(project_type, metadata)

        with self._db_session() as s:
            sess = ReviewSession(
                id=session_id, user_id=user_id,
                file_ids=_jstr([f.get("id", "") for f in file_id_entries]),
                project_type=project_type,
                project_name=metadata.get("project_name", ""),
                project_scale=metadata.get("project_scale", ""),
                skill_id=skill_id, batch_id=batch_id,
                knowledge_scope=_jstr(knowledge_scope),
                stats=_jstr({"turns": 0}),
            )
            s.add(sess)

            # 文件已提取与否决定派发路径
            all_extracted = True
            for entry in file_id_entries:
                fid = entry.get("id", "")
                row = s.get(ReviewFile, fid)
                if row is None or not (row.extracted_text or "").strip():
                    all_extracted = False
                    break

        self._set_running(session_id)

        if all_extracted:
            self._dispatch_first_turn(session_id, session_id, skill_text,
                                      knowledge_scope, metadata)
            self._sse(session_id, "session_created",
                      {"task_status": "queued", "queue": QUEUE_REVIEW})
        else:
            # Path B: 需提取 → 后台提取（extracting 事件）→ 完成后自动投首轮
            self._sse(session_id, "session_created",
                      {"task_status": "extracting"})
            self._extract_in_background(session_id, file_id_entries, skill_text,
                                        knowledge_scope, metadata)

        return {"session_id": session_id, "needs_extraction": not all_extracted}

    def _extract_in_background(self, session_id: str, file_id_entries: list[dict],
                               skill_text: str, knowledge_scope: list,
                               metadata: dict) -> None:
        """后台提取文件文本 → 完成后投首轮（与原项目 _sync_extract_to_workspace 同语义）。"""
        import threading

        def _run():
            try:
                extractor = self.ctx.get("extract")   # 平台协议, 换引擎零改动
                with self._db_session() as s:
                    for entry in file_id_entries:
                        fid = entry.get("id", "")
                        f = s.get(ReviewFile, fid)
                        if f is None or (f.extracted_text or "").strip():
                            continue
                        raw = self._storage().get(f.minio_path)
                        text = extractor.extract(raw, f.original_name or "")
                        self._sse(session_id, "extracting",
                                  {"stage": "extract", "file": f.original_name,
                                   "status": "done"})
                        f.extracted_text = text
                self._dispatch_first_turn(session_id, session_id, skill_text,
                                          knowledge_scope, metadata)
            except Exception as e:
                logger.exception(f"[review] 后台提取失败 session={session_id}")
                self._sse(session_id, "error", {"message": f"提取失败: {e}"})
                with self._db_session() as s:
                    sess = s.get(ReviewSession, session_id)
                    if sess:
                        sess.last_error = str(e)

        threading.Thread(target=_run, daemon=True).start()

    def _dispatch_first_turn(self, session_id: str, turn_id: str, skill_text: str,
                             knowledge_scope: list, metadata: dict) -> None:
        """创建首条 user 消息 + 投 review 队列（线程内联降级由任务函数处理）。"""
        user_message = self._build_first_message(metadata)
        self.save_message(session_id, turn_id, "user", user_message)
        self._enqueue_turn(session_id, turn_id, skill_text, knowledge_scope,
                           user_message, QUEUE_REVIEW)

    def _build_first_message(self, metadata: dict) -> str:
        parts = ["请对以下施工方案进行专业审查。"]
        if metadata.get("project_name"):
            parts.append(f"项目名称: {metadata['project_name']}")
        if metadata.get("project_type_cn"):
            parts.append(f"方案类型: {metadata['project_type_cn']}")
        parts.append("请按 Skill 规定的输出格式输出完整审查报告。")
        return "\n".join(parts)

    # ── 执行轮（核心）──

    def execute_turn(self, session_id: str, turn_id: str, skill_text: str,
                     knowledge_scope: list, user_message: str,
                     conversation_history: list | None = None,
                     lock_token: str = "", is_followup: bool = False) -> dict:
        """执行一轮审查：guard → 锁 → 工作区 → 引擎 → 报告 → 消息 → SSE。"""
        ctx = self.ctx
        cache = self._cache()

        # 0. 僵尸任务排队超时丢弃（对齐原项目 STALE_TASK_MAX_AGE）
        queued_at = cache.get(f"review:queued:{turn_id}")
        if queued_at:
            try:
                if time.time() - float(queued_at) > STALE_TASK_MAX_AGE:
                    logger.warning(f"[review] 任务排队超时丢弃: {turn_id}")
                    self._sse(session_id, "error", {"message": "任务排队超时, 已丢弃"})
                    self._clear_running(session_id)
                    return {"skipped": True, "reason": "stale_task"}
            except (TypeError, ValueError):
                pass

        # 1. turn 幂等守卫（防 Celery 重投递双跑）
        guard_key = f"review:turn:{turn_id}"
        if cache.get(guard_key):
            logger.warning(f"[review] turn 已执行过, 跳过: {turn_id}")
            return {"skipped": True, "session_id": session_id}
        cache.set(guard_key, "1", ttl=TURN_GUARD_TTL)

        # turn:started 标记（首次设, 硬超时判据）
        if not cache.get(f"review:turn_started:{session_id}"):
            cache.set(f"review:turn_started:{session_id}",
                      str(time.time()), ttl=TURN_STARTED_TTL)

        # 2. running 标记 + 会话锁（原子 SET NX, 防同会话并发执行双跑）
        self._set_running(session_id)
        lock_token = uuid.uuid4().hex[:8]
        if not self._acquire_session_lock(session_id, lock_token):
            raise RuntimeError(f"会话正在执行中（并发冲突）: {session_id}")

        heartbeat_stop = None
        try:
            # 3. 工作区 + materials 写入（首轮从 review_files.extracted_text）
            session_dir = setup_session_workspace(ctx, session_id)
            self._write_materials(session_id, session_dir)

            # 3.5 心跳（15s 续期 running/锁 TTL + bump updated_at, 长任务防自愈）
            heartbeat_stop = self._start_heartbeat(session_id, lock_token)

            # 4. 引擎事件 → 审查 SSE（首轮/追问共享; payload 字段对齐内核事件注册表）
            def _bridge(event: str, payload: dict) -> None:
                if event == "agent/tool_progress":
                    # 子代理/工具进度: 事件名动态（event_type.replace(".","_"), 对齐原项目）
                    evt = str(payload.get("event_type", "tool_progress")).replace(".", "_")
                    data = dict(payload.get("kw") or {})
                    data.setdefault("task_status", "running")
                    self._sse(session_id, evt, data)
                else:
                    self._sse(session_id, _ENGINE_EVENT_MAP.get(event, event),
                              {"content": payload.get("delta", "")})

            disposers = [
                ctx.on(evt, lambda p, e=evt: _bridge(e, p))
                for evt in _ENGINE_EVENT_MAP
            ]
            try:
                # 5. 工具上下文 + 引擎调用（5 次退避重试）
                from extensions.business.review.tools.save_review_report import (
                    set_review_context,
                )
                set_review_context(session_id=session_id,
                                   work_dir=session_dir, session=self)
                result = self._run_engine(user_message, conversation_history,
                                          skill_text, knowledge_scope, is_followup)

                # 6. 空报告重试一次（L2）
                report_content = _extract_report(result, conversation_history)
                if not report_content:
                    logger.warning("[review] 首轮空报告, L2 重试一次")
                    result = self._run_engine(user_message, conversation_history,
                                              skill_text, knowledge_scope, is_followup)
                    report_content = _extract_report(result, conversation_history)
            finally:
                for d in disposers:
                    try:
                        d()
                    except Exception:
                        pass

            # 7. 空报告校验（先于保存, 空报告不产生版本）
            if not report_content:
                raise RuntimeError("审查未产出最终报告（空报告）")

            # 8. 报告保存（storage + 版本+1）
            version, report_path = self._persist_report(
                session_id, report_content, result)

            # 9. 消息持久化（assistant + tool_calls）
            self._persist_engine_messages(session_id, turn_id, result,
                                          conversation_history)

            self._sse(session_id, "report_ready",
                      {"title": _extract_title(report_content) or "审查报告",
                       "size": len(report_content)})
            self._sse(session_id, "done", {
                "report_path": report_path,
                "report_version": version,
                "token_usage": result.get("token_usage", {}),
            })
            return {"version": version, "report_path": report_path}

        except Exception as e:
            logger.exception(f"[review] 审查执行失败 session={session_id}")
            self._sse(session_id, "error", {"message": str(e)})
            with self._db_session() as s:
                sess = s.get(ReviewSession, session_id)
                if sess:
                    sess.last_error = str(e)
            raise
        finally:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            self._clear_running(session_id)
            self._release_session_lock(session_id, lock_token)

    def _run_engine(self, user_message: str, conversation_history: list,
                    skill_text: str, knowledge_scope: list,
                    is_followup: bool) -> dict:
        """引擎调用 + 指数退避重试（封顶 30s）。"""
        loop = self._loop()
        last_err: Exception | None = None
        for attempt in range(1, MAX_ENGINE_RETRIES + 1):
            try:
                return loop.run_conversation(
                    user_message,
                    conversation_history=conversation_history or [],
                    system_prompt=self._build_system_prompt(
                        skill_text, knowledge_scope, is_followup),
                    toolsets=(
                        ["file", "standard_search", "context_engine",
                         "save_review_report", "delegation"]
                        if not is_followup else
                        ["file", "standard_search", "context_engine",
                         "save_review_report"]),
                )
            except Exception as e:
                last_err = e
                delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), 30)
                logger.warning(f"[review] 引擎调用第 {attempt} 次失败: {e}, "
                               f"{delay}s 后重试")
                time.sleep(delay)
        raise last_err or RuntimeError("引擎调用失败")

    def _build_system_prompt(self, skill_text: str, knowledge_scope: list,
                             is_followup: bool) -> str:
        """系统提示词 = Skill + 工具规则 + 子代理规则 + 工作区 + 知识 + 安全。"""
        from extensions.business.review.security import PromptGuard, ToolPolicy
        from extensions.business.review.paths import bash_path

        sp = skill_text or ""
        if skill_text and not is_followup:
            sp += ToolPolicy.first_turn_tool_rules()
        elif skill_text and is_followup:
            sp += ToolPolicy.followup_tool_rules()
            sp += ToolPolicy.followup_behavior_rules()
        else:
            sp += ToolPolicy.no_skill_tool_rules()
        sp += ToolPolicy.sub_agent_delegation_rules()
        if knowledge_scope:
            sp += ToolPolicy.knowledge_scope_rules(knowledge_scope)
        sp += PromptGuard.build_security_prompt()
        return sp

    def _write_materials(self, session_id: str, session_dir: str) -> None:
        """首轮把已提取的文件文本写入工作区 materials/（写前解锁, 写后锁回只读）。"""
        sandbox = self.ctx.get("sandbox")   # 平台文件权限保护
        materials_dir = os.path.join(session_dir, "materials")
        sandbox.unlock_dir(materials_dir)
        try:
            with self._db_session() as s:
                sess = s.get(ReviewSession, session_id)
                if not sess:
                    return
                for fid in sess.get_file_ids():
                    f = s.get(ReviewFile, fid)
                    if f and f.extracted_text:
                        doc_dir = os.path.join(materials_dir, f.file_type or "other")
                        os.makedirs(doc_dir, exist_ok=True)
                        base = os.path.splitext(f.original_name)[0] or f.id
                        target = os.path.join(doc_dir, f"{base}.md")
                        if not os.path.exists(target):
                            with open(target, "w", encoding="utf-8") as fp:
                                fp.write(f.extracted_text)
        finally:
            sandbox.lock_dir_readonly(materials_dir)

    # ── 报告持久化 ──

    def _persist_report(self, session_id: str, content: str, result: dict) -> tuple[int, str]:
        """报告存平台 storage（版本+1）+ DB 记录。返回 (version, path)。"""
        storage = self._storage()
        with self._db_session() as s:
            sess = s.get(ReviewSession, session_id)
            if sess is None:
                raise ValueError(f"会话不存在: {session_id}")
            version = sess.report_version + 1
            key = f"review:{session_id}:report:v{version}"
            storage.put(key, content.encode("utf-8"))
            versions = sess.get_report_versions()
            versions.append({"version": version, "title": _extract_title(content),
                             "minio_path": key, "size": len(content),
                             "created_at": datetime.now().isoformat()})
            sess.report_version = version
            sess.report_versions = _jstr(versions)
            sess.report_path = key
            sess.token_usage = _jstr(result.get("token_usage", {}))
        return version, key

    def _persist_engine_messages(self, session_id: str, turn_id: str, result: dict,
                                 conversation_history: list | None) -> None:
        """把本轮引擎 messages 持久化（assistant + tool, seq 全局递增）。

        与原项目一致: 保留 tool 消息（tool_call_id/name）, 确保追问历史完整;
        seq 用 session 级 _next_seq（原项目 _persist 同款）, 不每轮重置。
        """
        messages = result.get("messages", []) or []
        skip = len(conversation_history or []) + 1
        with self._db_session() as s:
            for msg in messages[skip:]:
                role = msg.get("role", "")
                if role not in ("assistant", "tool"):
                    continue
                seq = self._next_seq(s, session_id)
                self._insert_message(
                    s, session_id, turn_id, seq, role,
                    msg.get("content", ""),
                    tool_calls=msg.get("tool_calls"),
                    tool_call_id=msg.get("tool_call_id", ""),
                    name=msg.get("name", ""))

    def _insert_message(self, s, session_id: str, turn_id: str, seq: int, role: str,
                        content: str, tool_calls=None, tool_call_id: str = "",
                        name: str = "") -> None:
        s.add(ReviewMessage(session_id=session_id, turn_id=turn_id, seq=seq,
                            role=role, content=content or "",
                            tool_calls=_jstr(tool_calls) if tool_calls else "",
                            tool_call_id=tool_call_id, name=name))

    def save_message(self, session_id: str, turn_id: str, role: str, content: str) -> None:
        with self._db_session() as s:
            seq = self._next_seq(s, session_id)
            self._insert_message(s, session_id, turn_id, seq, role, content)

    def _next_seq(self, s, session_id: str) -> int:
        from sqlalchemy import func, select
        r = s.query(func.max(ReviewMessage.seq)).filter(
            ReviewMessage.session_id == session_id).scalar()
        return (r or 0) + 1

    def _build_conversation_history(self, session_id: str,
                                    exclude_turn_id: str = "") -> list[dict]:
        """构建 agent 对话历史（user + assistant + tool, 含 tool_calls 元数据）。

        与原项目 conversations._build_conversation_history 一致:
        保留 tool 消息和 tool_calls, 确保追问时模型能看到首轮操作过程
        （读文件/搜规范/调子代理）; exclude_turn_id 排除当前 turn
        （当前 user 消息作为 user_message 单独传, 避免重复）。
        """
        import json
        with self._db_session() as s:
            rows = (s.query(ReviewMessage)
                    .filter(ReviewMessage.session_id == session_id)
                    .order_by(ReviewMessage.seq).all())
        history: list[dict] = []
        for msg in rows:
            if exclude_turn_id and msg.turn_id == exclude_turn_id:
                continue
            entry = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = (
                    json.loads(msg.tool_calls)
                    if isinstance(msg.tool_calls, str) else msg.tool_calls)
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name:
                entry["name"] = msg.name
            history.append(entry)
        return history

    # ── 追问轮 ──

    def start_turn(self, session_id: str, message: str, turn_id: str | None = None) -> dict:
        """追问：门控（会话锁/陈旧恢复）→ 存 user 消息 → 投 followup 队列。"""
        if not self._can_followup(session_id):
            raise ValueError("FirstReviewIncompleteError: 首轮尚未完成, 不能追问")
        lock_token = uuid.uuid4().hex[:8]
        if not self._acquire_session_lock(session_id, lock_token):
            if self._force_recover_lock(session_id, lock_token):
                # 崩溃恢复（陈旧/硬超时）: 强清锁 + 恢复通知
                self._sse(session_id, "session_recovered",
                          {"task_status": "recovered", "message": "检测到任务中断, 已恢复"})
            else:
                raise ValueError("SessionBusyError: 会话正在执行中, 请稍后重试")
        try:
            turn_id = turn_id or uuid.uuid4().hex[:12]

            with self._db_session() as s:
                sess = s.get(ReviewSession, session_id)
                if sess is None:
                    raise ValueError(f"会话不存在: {session_id}")
                skill_text = load_skill(sess.skill_id) if sess.skill_id else ""
                knowledge_scope = sess.get_knowledge_scope()
                self.save_message(session_id, turn_id, "user", message)
                stats = sess.get_stats()
                stats["turns"] = stats.get("turns", 0) + 1
                sess.stats = _jstr(stats)

            # 构建追问历史（排除当前 turn; 当前消息作 user_message 单独传）
            conversation_history = self._build_conversation_history(
                session_id, exclude_turn_id=turn_id)
            self._enqueue_turn(session_id, turn_id, skill_text, knowledge_scope,
                               message, QUEUE_FOLLOWUP, conversation_history)
            return {"session_id": session_id, "turn_id": turn_id}
        finally:
            self._release_session_lock(session_id, lock_token)

    def _can_followup(self, session_id: str) -> bool:
        """首轮须已产出 assistant 消息才可追问。"""
        with self._db_session() as s:
            return s.query(ReviewMessage).filter(
                ReviewMessage.session_id == session_id,
                ReviewMessage.role == "assistant").count() > 0

    def _enqueue_turn(self, session_id: str, turn_id: str, skill_text: str,
                      knowledge_scope: list, user_message: str, queue: str,
                      conversation_history: list | None = None) -> None:
        """投递审查轮（任务名常量; worker 同名任务 / 线程内联由应用壳注册）。"""
        from extensions.business.review.task import TASK_EXECUTE_REVIEW
        # 排队时间戳（僵尸任务入口超时判据）
        self._cache().set(f"review:queued:{turn_id}", str(time.time()),
                          ttl=STALE_TASK_MAX_AGE + 60)
        self._sse(session_id, "queue_status",
                  {"task_status": "queued", "queue": queue, "is_queued": True})
        self._jobs().enqueue(
            TASK_EXECUTE_REVIEW,
            args=[session_id, turn_id, skill_text, knowledge_scope,
                  user_message, conversation_history, queue],
            queue=queue)

    # ── 查询 ──

    def get_report(self, session_id: str, versions: list[int] | None = None) -> dict:
        with self._db_session() as s:
            sess = s.get(ReviewSession, session_id)
            if sess is None:
                raise ValueError(f"会话不存在: {session_id}")
            storage = self._storage()
            known = {v["version"]: v for v in sess.get_report_versions()}
            out = []
            for v in (versions or [sess.report_version]):
                key = f"review:{session_id}:report:v{v}"
                try:
                    content = storage.get(key).decode("utf-8")
                    meta = known.get(v, {})
                    out.append({"version": v, "title": meta.get("title") or _extract_title(content),
                                "created_at": meta.get("created_at"),
                                "content": content, "minio_path": key})
                except Exception:
                    continue
            return {"versions": versions or [sess.report_version], "reports": out}

    def get_chat_messages(self, session_id: str) -> dict:
        """聊天视图: 每轮留最后一条 assistant（对齐原项目 get_chat_messages）。"""
        with self._db_session() as s:
            rows = (s.query(ReviewMessage)
                    .filter(ReviewMessage.session_id == session_id)
                    .order_by(ReviewMessage.seq).all())
        per_turn: dict[str, list] = {}
        for m in rows:
            per_turn.setdefault(m.turn_id, []).append(m)
        out = []
        for tid in sorted(per_turn):
            msgs = per_turn[tid]
            users = [m.content for m in msgs if m.role == "user"]
            assistants = [m.content for m in msgs if m.role == "assistant"]
            entry = {"turn_id": tid}
            if users:
                entry["user"] = users[-1]
            if assistants:
                entry["assistant"] = assistants[-1]
            out.append(entry)
        return {"messages": out}

    def get_status(self, session_id: str) -> dict:
        with self._db_session() as s:
            sess = s.get(ReviewSession, session_id)
            if sess is None:
                raise ValueError(f"会话不存在: {session_id}")
            running = bool(self._cache().get(f"review:running:{session_id}"))
            status = self._derive_task_status(sess, running)
            return {"session_id": session_id, "task_status": status,
                    "is_stale": self._is_stale(session_id),
                    "last_error": sess.last_error,
                    "report_version": sess.report_version,
                    "available_versions": sess.get_report_versions(),
                    "updated_at": str(sess.updated_at)}

    def _derive_task_status(self, sess: ReviewSession, running: bool) -> str:
        """状态推导（对齐原项目 _derive_task_status）。

        非 running → error(有 last_error) / completed;
        running → 有 trace 步骤(running) / 仅 extracting / 否则 queued。
        """
        if not running:
            return "error" if sess.last_error else "completed"
        events = [e.get("event") for e in sess.get_progress()]
        if any(e in ("thinking", "action", "message", "report_ready") for e in events):
            return "running"
        if "extracting" in events:
            return "extracting"
        return "queued"

    def cleanup_incomplete_turns(self, session_id: str) -> None:
        """清理有 user 无 assistant 的 turn（对齐原项目, 时间护栏 30min）。"""
        with self._db_session() as s:
            turns = set()
            for m in (s.query(ReviewMessage)
                      .filter(ReviewMessage.session_id == session_id).all()):
                turns.add(m.turn_id)
            for tid in turns:
                has_user = (s.query(ReviewMessage)
                            .filter(ReviewMessage.session_id == session_id,
                                    ReviewMessage.turn_id == tid,
                                    ReviewMessage.role == "user").count())
                has_assistant = (s.query(ReviewMessage)
                                 .filter(ReviewMessage.session_id == session_id,
                                         ReviewMessage.turn_id == tid,
                                         ReviewMessage.role == "assistant").count())
                if has_user and not has_assistant:
                    s.query(ReviewMessage).filter(
                        ReviewMessage.session_id == session_id,
                        ReviewMessage.turn_id == tid).delete()

    def get_session(self, session_id: str, include_report: bool = True) -> dict:
        with self._db_session() as s:
            sess = s.get(ReviewSession, session_id)
            if sess is None:
                raise ValueError(f"会话不存在: {session_id}")
            return {
                "session_id": sess.id,
                "project_type": sess.project_type,
                "project_name": sess.project_name,
                "skill_id": sess.skill_id,
                "knowledge_scope": sess.get_knowledge_scope(),
                "report_version": sess.report_version,
                "report_versions": sess.get_report_versions(),
                "last_error": sess.last_error,
                "status": self.get_status(session_id)["task_status"],
                "turns": sess.get_stats().get("turns", 0),
            }

    def get_messages(self, session_id: str) -> dict:
        with self._db_session() as s:
            rows = (s.query(ReviewMessage)
                    .filter(ReviewMessage.session_id == session_id)
                    .order_by(ReviewMessage.seq).all())
            return {"messages": [
                {"turn_id": m.turn_id, "seq": m.seq, "role": m.role,
                 "content": m.content} for m in rows]}

    # ── 内部工具 ──

    def _set_running(self, session_id: str) -> None:
        self._cache().set(f"review:running:{session_id}", "1", ttl=RUNNING_TTL)

    def _clear_running(self, session_id: str) -> None:
        self._cache().set(f"review:running:{session_id}", "", ttl=1)

    def _acquire_session_lock(self, session_id: str, token: str) -> bool:
        """原子会话锁（SET NX）: 成功 True。

        并发正确性: 不做"running 消失即强清"——那会让两个并发 start_turn
        （都不设 running）同时拿到锁。崩溃残留靠陈旧/硬超时判据恢复（见下）。
        """
        return self._cache().set_nx(
            f"review:lock:{session_id}", token, ttl=SESSION_LOCK_TTL)

    def _release_session_lock(self, session_id: str, token: str) -> None:
        """释放会话锁（仅当持有者 token 匹配; 用 delete 而非 set('')——空串会挡 set_nx）。"""
        cache = self._cache()
        lock_key = f"review:lock:{session_id}"
        if cache.get(lock_key) == token:
            cache.delete(lock_key)

    def _force_recover_lock(self, session_id: str, token: str) -> bool:
        """锁被占但判据显示崩溃 → 强清恢复（对齐原项目 _is_stale/_force_clear）。"""
        if not (self._is_stale(session_id) or self._is_turn_hard_expired(session_id)):
            return False
        cache = self._cache()
        cache.set(f"review:lock:{session_id}", token, ttl=SESSION_LOCK_TTL)  # 覆盖锁
        cache.set(f"review:running:{session_id}", "", ttl=1)                 # 清 running
        return True

    def _is_stale(self, session_id: str) -> bool:
        """updated_at 陈旧判定（> STALE_TIMEOUT 视为崩溃残留）。"""
        try:
            with self._db_session() as s:
                sess = s.get(ReviewSession, session_id)
                if not sess or not sess.updated_at:
                    return False
                return time.time() - sess.updated_at.timestamp() > STALE_TIMEOUT
        except Exception:
            return False

    def _is_turn_hard_expired(self, session_id: str) -> bool:
        """turn 硬超时（turn:started 超过 TURN_HARD_TIMEOUT）。"""
        started = self._cache().get(f"review:turn_started:{session_id}")
        if not started:
            return False
        try:
            return time.time() - float(started) > TURN_HARD_TIMEOUT
        except (TypeError, ValueError):
            return False

    def _start_heartbeat(self, session_id: str, lock_token: str) -> threading.Event:
        """15s 心跳线程: 续期 running/锁 TTL + bump updated_at + heartbeat 事件。

        兜底单次超长 LLM 调用（>600s 无新 step → 不误判陈旧而恢复）。
        """
        stop = threading.Event()

        def _beat():
            while not stop.wait(HEARTBEAT_INTERVAL):
                try:
                    self._cache().set(f"review:running:{session_id}", "1",
                                      ttl=RUNNING_TTL)
                    self._cache().set(f"review:lock:{session_id}", lock_token,
                                      ttl=SESSION_LOCK_TTL)
                    self._bump_updated_at(session_id)
                    self._sse(session_id, "heartbeat", {"task_status": "running"})
                except Exception:
                    pass

        t = threading.Thread(target=_beat, daemon=True,
                             name=f"review-hb-{session_id[:8]}")
        t.start()
        return stop


def _jstr(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
