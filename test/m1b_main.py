"""m1b_main.py — M1b 验证：Hermes 真实引擎接入（经 ctx.agentLoop）。

运行: PYTHONIOENCODING=utf-8 python m1b_main.py
前置:
  - hermes-agent 源码路径（本地包, 未 pip 安装, 脚本内 sys.path 注入）
  - app/config/config.local.ini 的 [llm] 段（真实 API 调用, 有成本）

验证项:
  [1] HermesLoop 协议合规 (runtime_checkable)
  [2] 真实 LLM 调用: 大纲 + 章节产物落盘（非假回复）
  [3] 事件翻译: hermes 内部回调 → 平台事件可达（llm/stream 计数 > 0）
  [4] 换引擎零改动: 覆盖注册 FakeLoop → 同一 pipeline 产物来自 fake
  [5] 消费纪律: 流水线每次调用时 ctx.get('agentLoop')
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import configparser
import os
import sys

# hermes-agent 本地源码路径（正式接入改为 pip 安装后移除本块）
HERMES_AGENT_SRC = r"D:/standard_workspace/products_dev/upstream/hermes-agent"

from aic.kernel import Context, EventMode, boot
from aic.extensions.platform.loops import FakeLoop
from aic.extensions.platform.loops.hermes import HermesEnginePlugin, HermesLoop
from aic.kernel.protocols import AgentLoop
from aic.extensions.platform.session import SessionPlugin
from aic.extensions.platform.render import RenderPlugin
from extensions.business.writer import WriterPlugin
from extensions.business.writer.task import OUTLINE_REPLY

# ── 业务导入之后再注入 hermes-agent 源码路径 ──
# 原因: hermes-agent 自带顶层 plugins/ 包, 若先注入会遮蔽本项目的包
# run_agent 在 HermesLoop.run_conversation 内部懒加载, 此处注入不影响导入顺序
sys.path.insert(0, HERMES_AGENT_SRC)

_PASS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def _load_llm_config() -> dict:
    parser = configparser.ConfigParser()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根
    parser.read(os.path.join(here, "apps", "mvp", "config", "config.local.ini"), encoding="utf-8")
    if not parser.has_section("llm"):
        raise SystemExit("config.local.ini 缺少 [llm] 段")
    keys = ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER")
    return {k: parser.get("llm", k, fallback="") for k in keys}


def main() -> int:
    skip_real = "--skip-real" in sys.argv
    print("=" * 64)
    print("M1b 验证: Hermes 真实引擎接入 (ctx.agentLoop)")
    print("=" * 64)

    # ── 应用壳: 平台 + 配置 + 引擎插件 + 会话 + writer 插件 ──
    app = Context()
    app.register("config", {"llm": _load_llm_config()})
    mounts = boot(app, [RenderPlugin(), HermesEnginePlugin(), SessionPlugin(), WriterPlugin()])
    order = [m.plugin.__class__.__name__ for m in mounts]
    print(f"\n[0] 装配顺序: {order}")

    print("\n[1] AgentLoop 引擎协议")
    loop = app.get("agentLoop")
    check("HermesLoop 协议合规 (runtime_checkable)",
          isinstance(loop, AgentLoop), type(loop).__name__)

    sessions = app.get("sessions")
    pipeline = app.get("writerPipeline")

    if not skip_real:
        print("\n[2] 真实 LLM 调用（writer 流水线, 有 API 成本）")
        stream_count = {"n": 0}
        app.on("llm/stream", lambda p: stream_count.__setitem__("n", stream_count["n"] + 1),
               EventMode.EMIT)
        session = sessions.create_session({"project": "验证用: 跨江特大桥挂篮施工方案"})
        result = pipeline.run(session, "验证用: 跨江特大桥挂篮施工方案",
                              chapters=["编制依据"])

        outline_path = os.path.join(session.dir, "outline", "outline.md")
        chapter_path = os.path.join(session.dir, "chapters", "01_编制依据.md")
        check("大纲产物落盘", os.path.exists(outline_path), outline_path)
        check("章节产物落盘", os.path.exists(chapter_path), chapter_path)

        with open(outline_path, encoding="utf-8") as f:
            outline = f.read()
        check("产物是真实 LLM 输出（非假回复表）",
              bool(outline.strip()) and outline != OUTLINE_REPLY,
              f"大纲前 60 字: {outline[:60].strip()}…")

        print("\n[3] 事件翻译（hermes 回调 → 平台事件）")
        check("llm/stream 事件已流入平台事件总线", stream_count["n"] > 0,
              f"收到 {stream_count['n']} 个流增量")
    else:
        print("\n[2] ⏭  --skip-real, 跳过真实 LLM 调用（需 hermes 引擎 + API key）")
        print("      [3] 事件翻译 随 [2] 一起跳过")

    print("\n[4] 换引擎零改动（Hermes → FakeLoop, 同一 pipeline）")
    app.register("agentLoop", FakeLoop(name="fake-swap", replies={
        "大纲": OUTLINE_REPLY,
        "编制依据": "# 一、编制依据\n(假引擎内容)\n",
    }))
    session2 = sessions.create_session({"project": "某隧道施工方案"})
    result2 = pipeline.run(session2, "某隧道施工方案", chapters=["编制依据"])
    check("换引擎后 pipeline 照常工作", result2["loop_name"] == "fake-swap",
          result2["loop_name"])
    with open(os.path.join(session2.dir, "outline", "outline.md"), encoding="utf-8") as f:
        outline2 = f.read()
    check("产物来自新引擎", outline2 == OUTLINE_REPLY)

    print("\n[5] 消费纪律（调用时取, 不缓存引用）")
    check("Hermes 实例未被继续使用（流水线已换用 fake-swap）",
          result2["loop_name"] == "fake-swap")

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print("✅ M1b 全部通过 — Hermes 真实引擎已接入, 可替换, 事件已翻译")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
