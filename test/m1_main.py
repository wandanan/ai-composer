"""m1_main.py — M1a 验证：agentLoop 引擎协议 + 最小编写流水线（不依赖 LLM）。

运行: PYTHONIOENCODING=utf-8 python m1_main.py
验证项:
  [1] AgentLoop 协议: FakeLoop 合规 (runtime_checkable)
  [2] 最小编写流水线: 大纲 + 第一章 → md 产物落盘
  [3] 引擎可替换: 换 FakeLoop v2 → 同一流水线零改动, 产物来自新引擎
  [4] 消费纪律: 流水线每次调用时 ctx.get('agentLoop')（旧引擎不再被使用）
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import os

from kernel import Context, boot
from extensions.platform.loops import FakeLoop
from kernel.protocols import AgentLoop
from extensions.platform.session import SessionPlugin
from extensions.platform.render import RenderPlugin
from extensions.business.writer import WriterPlugin
from extensions.business.writer.task import CHAPTER_REPLY, OUTLINE_REPLY

_PASS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=" * 64)
    print("M1a 验证: agentLoop 引擎协议 + 最小编写流水线")
    print("=" * 64)

    # ── 应用壳: 平台 + 引擎(默认) + 会话 + writer 插件 ──
    app = Context()
    v1 = FakeLoop(name="fake-v1", replies={
        "大纲": OUTLINE_REPLY,
        "编制依据": CHAPTER_REPLY,
    })
    app.register("agentLoop", v1)                      # 平台注册引擎（可被覆盖）
    boot(app, [RenderPlugin(), SessionPlugin(), WriterPlugin()])

    print("\n[1] AgentLoop 引擎协议")
    loop = app.get("agentLoop")
    check("FakeLoop 协议合规 (runtime_checkable)",
          isinstance(loop, AgentLoop), type(loop).__name__)

    print("\n[2] 最小编写流水线（大纲 → 第一章 → md 产物）")
    sessions = app.get("sessions")
    session = sessions.create_session({"project": "沿江高速特大桥挂篮施工方案"})
    pipeline = app.get("writerPipeline")
    result = pipeline.run(session, "沿江高速特大桥挂篮施工方案", chapters=["编制依据"])
    artifacts_dir = session.dir

    outline_path = os.path.join(artifacts_dir, "outline", "outline.md")
    chapter_path = os.path.join(artifacts_dir, "chapters", "01_编制依据.md")
    check("大纲产物落盘", os.path.exists(outline_path), outline_path)
    check("章节产物落盘", os.path.exists(chapter_path), chapter_path)

    with open(outline_path, encoding="utf-8") as f:
        outline = f.read()
    with open(chapter_path, encoding="utf-8") as f:
        chapter = f.read()
    check("大纲内容 = 引擎确定性输出", outline == OUTLINE_REPLY)
    check("章节内容 = 引擎确定性输出", chapter == CHAPTER_REPLY)
    check("流水线使用的引擎 = fake-v1", result["loop_name"] == "fake-v1", result["loop_name"])

    print("\n[3] 引擎可替换（消费方零改动）")
    app.register("agentLoop", FakeLoop(name="fake-v2", replies={   # 换引擎 = 重新注册
        "大纲": "# v2 大纲\n## 全新章节结构\n",
        "编制依据": "# v2 编制依据\nv2 内容\n",
    }))
    session2 = sessions.create_session({"project": "某隧道施工方案"})
    result2 = pipeline.run(session2, "某隧道施工方案", chapters=["编制依据"])
    check("换引擎后 pipeline 照常工作", result2["loop_name"] == "fake-v2", result2["loop_name"])
    with open(os.path.join(session2.dir, "outline", "outline.md"), encoding="utf-8") as f:
        outline2 = f.read()
    check("产物来自新引擎", outline2.startswith("# v2 大纲"))

    print("\n[4] 消费纪律（调用时取, 不缓存引用）")
    check("旧引擎 v1 未被继续使用（调用数为 4: 理解/大纲/章节/合并）",
          len(v1.calls) == 4, f"v1 被调用 {len(v1.calls)} 次")

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print("✅ M1a 全部通过 — 引擎协议成立, 流水线可换引擎零改动")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
