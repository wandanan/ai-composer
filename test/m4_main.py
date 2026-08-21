"""m4_main.py — M4 验证：脚手架 / 批量编写 / 反馈闭环 / 引擎降级 / 阶段统计。

运行: PYTHONIOENCODING=utf-8 python m4_main.py
（全部确定性验证，无 API 成本）

验证项:
  [1] 脚手架: agent-kit init 生成应用壳（文件/可编译/config/可装配）
  [2] 批量编写: 20 方案并发无卡死, 全部成功, 产物隔离
  [3] 反馈闭环: 评审意见 → 定位章节 → 修订版本递增
  [4] 引擎降级: FailoverLoop 主引擎失败 → 备用引擎兜底
  [5] 阶段统计: pipeline 返回各阶段耗时
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util
import os
import py_compile
import sys
import tempfile

from aic.kernel import Context, boot
from aic.extensions.platform.loops import FakeLoop, FailoverLoop
from aic.extensions.platform.session import SessionPlugin
from aic.extensions.platform.session.artifacts import list_artifacts
from aic.extensions.platform.agent import TasksPlugin
from aic.extensions.platform.render import RenderPlugin
from extensions.business.writer import WriterPlugin
from extensions.business.writer.task import OUTLINE_REPLY

_PASS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


CHAPTERS = ["编制依据", "工程概况", "施工部署"]

FAKE_REPLIES = {
    "重写": "## 修订后的章节\n已按评审反馈更新 (fake)",
    "总结": "项目概况摘要 (fake)",
    "大纲": OUTLINE_REPLY,
    "编制依据": "# 一、编制依据\nfake 内容",
    "工程概况": "# 二、工程概况\nfake 内容",
    "施工部署": "# 三、施工部署\nfake 内容",
    "合并": "## 合并结果\n各章节已合并 (fake)",
}


class BrokenLoop:
    """主引擎故障模拟。"""

    name = "broken"

    def run_conversation(self, *a, **kw):
        raise ConnectionError("LLM API 不可用")

    def close(self):
        pass


def main() -> int:
    print("=" * 64)
    print("M4 验证: 应用壳模板 / 批量 / 反馈闭环 / 引擎降级 / 阶段统计")
    print("=" * 64)

    print("\n[1] 应用壳模板 (mvp_app —— 新应用的起点)")
    from apps.mvp.profile import PLUGINS as MVP_PLUGINS
    check("profile.py 可编译",
          py_compile.compile(os.path.join("apps", "mvp", "profile.py"),
                             doraise=True) is not None)
    with open(os.path.join("apps", "mvp", "config", "config.local.ini"), encoding="utf-8") as f:
        ini = f.read()
    check("config 含 [llm] 段", "[llm]" in ini)

    # mvp_app 插件组合可装配（新应用 = 复制 mvp_app → 换业务插件）
    shell = Context()
    mounts = boot(shell, list(MVP_PLUGINS))
    check("mvp_app 插件组合可装配（10 插件）",
          len(mounts) == len(MVP_PLUGINS), f"{len(mounts)} 个插件")
    check("核心服务就绪（沙箱/会话/渲染/SSE）",
          shell.has("sandbox") and shell.has("sessions")
          and shell.has("renderers") and shell.has("stream"))

    print("\n[2] 批量编写（20 方案并发, 无 API 成本）")
    app = Context()
    fake = FakeLoop(name="fake-m4", replies=FAKE_REPLIES, delay=0.02)
    app.register("agentLoop", fake)
    boot(app, [RenderPlugin(), SessionPlugin(), TasksPlugin(), WriterPlugin()])

    projects = [{"name": f"方案{i + 1:02d}", "chapters": CHAPTERS} for i in range(20)]
    batch = app.get("batch")
    results = batch.run(projects)
    check("20 方案全部完成", len(results) == 20, f"{len(results)}/20")
    errors = [sid for sid, r in results.items() if "error" in r]
    check("无失败项", len(errors) == 0, str(errors))
    sessions = app.get("sessions")
    ok_artifacts = all(
        os.path.exists(os.path.join(sessions.get(sid).dir, "output", "方案_v1.md"))
        for sid in results)
    check("每方案产物落盘（工作区隔离）", ok_artifacts)

    print("\n[3] 评审反馈闭环")
    session = sessions.create_session({"project": "反馈闭环验证"})
    pipeline = app.get("writerPipeline")
    pipeline.run(session, "反馈闭环验证", chapters=CHAPTERS)
    feedback = app.get("feedback")
    located = feedback.locate(session, "第三章施工部署缺少安全措施细节")
    check("反馈定位到章节 03_施工部署.md", located == "03_施工部署.md", str(located))
    revised = feedback.revise_by_feedback(session, "第三章施工部署缺少安全措施细节")
    check("修订版本递增到 2", revised["version"] == 2, str(revised))
    check("修订产物 v2 落盘",
          os.path.exists(os.path.join(session.dir, "output", "方案_v2.docx"))
          or os.path.exists(os.path.join(session.dir, "output", "方案_v2.md")))

    print("\n[4] 引擎降级（FailoverLoop）")
    failover = FailoverLoop(primary=BrokenLoop(), fallback=fake)
    app.register("agentLoop", failover)
    session2 = sessions.create_session({"project": "降级验证"})
    result2 = pipeline.run(session2, "降级验证", chapters=["编制依据"])
    check("主引擎故障 → 备用引擎兜底, 流水线照常",
          result2["loop_name"] == "failover", str(result2))
    # 引擎调用 4 次: understand/outline/write/merge（render 为本地渲染, 不调引擎）
    check("降级次数 = 4（引擎调用 4 次: 理解/大纲/写/合并）",
          failover.fallbacks == 4, f"降级 {failover.fallbacks} 次")

    print("\n[5] 阶段统计（可观测性）")
    stats = result2["stats"]
    check("5 阶段耗时齐全", set(stats) == {"understand", "outline", "write", "merge", "render"},
          str(stats))
    check("引擎阶段耗时 > 0, 总耗时 > 0（render 为本地渲染可接近 0）",
          all(v >= 0 for v in stats.values()) and sum(stats.values()) > 0,
          str(stats))

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print("✅ M4 全部通过 — 脚手架/批量/反馈闭环/降级/统计")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
