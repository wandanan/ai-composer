"""m2_main.py — M2 验证：完整 5 阶段流水线 + 修订闭环 + 真实引擎抽验。

运行: PYTHONIOENCODING=utf-8 python m2_main.py [--skip-real]
前置: [5] 需 config.local.ini 的 LLM 配置（约 5 次 API 调用）；--skip-real 跳过 [5]

验证项:
  [1] 装配与会话服务: inject 顺序 (Session→Writer) + ctx.sessions 工作
  [2] 5 阶段流水线 (FakeLoop): 阶段事件序列 + 章节状态 + 产物齐全
  [3] 分章并行: fake 引擎实测并发 >= 2
  [4] 修订闭环: 重写章节 → draft_v2 + 方案_v2, v1 保留
  [5] 真实引擎抽验 (Hermes, 沙箱挂载): 2 章节完整流水线, 产物落盘, 根目录零新文件
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import configparser
import os
import sys

HERMES_AGENT_SRC = r"D:/standard_workspace/products_dev/upstream/hermes-agent"

from kernel import Context, EventMode, boot
from extensions.platform.loops import FakeLoop, HermesLoop
from extensions.platform.security.sandbox import SandboxPlugin
from extensions.platform.session import SessionPlugin
from extensions.platform.session.artifacts import list_artifacts
from extensions.business.writer import WriterPlugin
from extensions.business.writer.pipeline import WriterPipeline
from extensions.business.writer.task import OUTLINE_REPLY

sys.path.insert(0, HERMES_AGENT_SRC)  # 业务导入后再注入 hermes 源码路径（plugins 遮蔽规避）

_PASS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def _load_llm_config() -> dict:
    parser = configparser.ConfigParser()
    here = os.path.dirname(os.path.abspath(__file__))
    parser.read(os.path.join(here, "app", "config", "config.local.ini"), encoding="utf-8")
    keys = ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER")
    return {k: parser.get("llm", k, fallback="") for k in keys}


CHAPTERS = ["编制依据", "工程概况", "施工部署"]

# 键序敏感: "重写" 必须排最前——revise prompt 含章节名(施工部署), 若其在前会先命中
FAKE_REPLIES = {
    "重写": "## 修订后的章节\n已按评审反馈更新 (fake)",
    "总结": "项目概况摘要 (fake)",
    "大纲": OUTLINE_REPLY,
    "编制依据": "第一章内容: 编制依据 (fake)",
    "工程概况": "第二章内容: 工程概况 (fake)",
    "施工部署": "第三章内容: 施工部署 (fake)",
    "合并": "## 合并结果\n各章节已合并并完成一致性校验 (fake)",
}


def main() -> int:
    skip_real = "--skip-real" in sys.argv
    print("=" * 64)
    print("M2 验证: 完整 5 阶段流水线 + 修订闭环" + ("（跳过真实引擎抽验）" if skip_real else ""))
    print("=" * 64)

    # ── 应用壳: 平台 + 假引擎 + 沙箱 + 会话 + writer 插件 ──
    app = Context()
    fake = FakeLoop(name="fake-m2", replies=FAKE_REPLIES, delay=0.05)  # 模拟耗时使并发可观测
    app.register("agentLoop", fake)
    mounts = boot(app, [SandboxPlugin(), SessionPlugin(), WriterPlugin()])
    order = [m.plugin.__class__.__name__ for m in mounts]
    print(f"\n[1] 装配: {order}")
    check("inject 推导: 沙箱/会话先于 WriterPlugin 挂载",
          order == ["SandboxPlugin", "SessionPlugin", "WriterPlugin"], str(order))

    sessions = app.get("sessions")
    session = sessions.create_session({"project": "跨江特大桥挂篮施工方案"})
    check("会话服务: 会话创建 + 工作区目录",
          os.path.isdir(session.dir), session.dir)

    # 事件监听
    phases_seen: list[str] = []
    chapters_done: list[str] = []
    app.on("pipeline/phase", lambda p: phases_seen.append(p["phase"]), EventMode.EMIT)
    app.on("chapter/status", lambda p: chapters_done.append(p["chapter"]), EventMode.EMIT)

    print("\n[2] 5 阶段流水线（FakeLoop 确定性）")
    pipeline = app.get("writerPipeline")
    result = pipeline.run(session, "跨江特大桥挂篮施工方案", chapters=CHAPTERS)
    check("阶段事件序列完整", phases_seen == list(WriterPipeline.PHASES), str(phases_seen))
    check("章节状态事件 3 次", len(chapters_done) == 3, str(chapters_done))

    sdir = session.dir
    check("summary 产物落盘", os.path.exists(os.path.join(sdir, "summary", "summary.md")))
    check("outline 产物落盘", os.path.exists(os.path.join(sdir, "outline", "outline.md")))
    chapter_files = list_artifacts(sdir, "chapters")
    check("3 章产物齐全", chapter_files == ["01_编制依据.md", "02_工程概况.md", "03_施工部署.md"],
          str(chapter_files))
    check("合并稿 v1 落盘", os.path.exists(os.path.join(sdir, "merged", "draft_v1.md")))
    check("渲染文档 v1 落盘", os.path.exists(os.path.join(sdir, "output", "方案_v1.md")))
    check("流水线摘要: 版本=1 章节=3 引擎=fake-m2",
          result["version"] == 1 and result["chapters"] == 3 and result["loop_name"] == "fake-m2",
          str(result))

    print("\n[3] 分章并行（引擎实测并发度）")
    check("并行度 >= 2（3 章并发执行）", fake.max_concurrent >= 2,
          f"实测最大并发 {fake.max_concurrent}")

    print("\n[4] 修订闭环（评审反馈 → 重写 → 重合并 → 重渲染）")
    revised = pipeline.revise(session, "第三章施工部署缺少安全措施细节", "03_施工部署.md")
    check("修订版本 = 2", revised["version"] == 2, str(revised))
    with open(os.path.join(sdir, "chapters", "03_施工部署.md"), encoding="utf-8") as f:
        ch3 = f.read()
    check("第三章已按反馈重写", "评审反馈" in ch3 or "修订" in ch3, ch3[:40])
    check("draft_v2 落盘", os.path.exists(os.path.join(sdir, "merged", "draft_v2.md")))
    check("方案_v2 落盘", os.path.exists(os.path.join(sdir, "output", "方案_v2.md")))
    check("历史版本保留 (v1 未覆盖)",
          os.path.exists(os.path.join(sdir, "merged", "draft_v1.md"))
          and os.path.exists(os.path.join(sdir, "output", "方案_v1.md")))
    check("修订触发状态事件 (done×3 + revised×1)",
          len(chapters_done) == 4 and chapters_done[-1] == "03_施工部署.md",
          str(chapters_done))

    print("\n[5] 真实引擎抽验（Hermes + 沙箱, 约 5 次 API）")
    if skip_real:
        print("  ⏭  --skip-real, 跳过真实引擎抽验")
    else:
        llm = _load_llm_config()
        app.register("agentLoop", HermesLoop(ctx=app, model=llm["LLM_MODEL"],
                                             api_key=llm["LLM_API_KEY"],
                                             base_url=llm["LLM_BASE_URL"]))
        # 沙箱: 会话工作区注册为 agent 文件边界
        sandbox = app.get("sandbox")
        session2 = sessions.create_session({"project": "真实抽验: 某隧道施工方案"})
        sandbox.set_workspace(session2.dir)
        os.environ["TERMINAL_CWD"] = session2.dir

        root_before = set(os.listdir("."))
        result2 = pipeline.run(session2, "真实抽验: 某隧道施工方案",
                               chapters=["编制依据", "工程概况"])
        root_after = set(os.listdir("."))
        os.environ.pop("TERMINAL_CWD", None)

        check("真实引擎完整流水线跑通", result2["loop_name"] == "hermes", str(result2))
        check("真实产物落盘（大纲/2 章/合并/渲染）",
              os.path.exists(os.path.join(session2.dir, "outline", "outline.md"))
              and len(list_artifacts(session2.dir, "chapters")) == 2
              and os.path.exists(os.path.join(session2.dir, "merged", "draft_v1.md"))
              and os.path.exists(os.path.join(session2.dir, "output", "方案_v1.md")))
        new_outside = [f for f in (root_after - root_before) if not f.startswith("m2_")]
        check("沙箱生效: 项目根目录零新文件（越界写被拦）",
              len(new_outside) == 0, str(new_outside))
        for f in new_outside:  # 保险清理
            os.remove(os.path.join(".", f))

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        tail = "（真实引擎抽验未跑）" if skip_real else "（含真实引擎抽验）"
        print(f"✅ M2 全部通过 — 5 阶段流水线 + 修订闭环 {tail}")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
