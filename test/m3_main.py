"""m3_main.py — M3 验证：docx 渲染扩展点 + 模板/范例知识注入。

运行: PYTHONIOENCODING=utf-8 python m3_main.py [--skip-real]
前置: [6] 需 config.local.ini 的 LLM 配置（1 次 API）

验证项:
  [1] 渲染注册表: ctx.renderers + DocxRenderer 注册 + 协议合规
  [2] md→docx: 标题/表格/列表/粗体/页眉 转换正确
  [3] 模板样式: 标题字号/颜色按 TEMPLATE_STYLE
  [4] 知识注入: scope 返回模板+范例目录, 资源文件存在
  [5] pipeline 集成: 方案_v1.md + 方案_v1.docx 双产物
  [6] 真实引擎模板抽验 (1 次 API): 输出遵循模板章节结构
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

from docx import Document as DocxDocument
from docx.shared import RGBColor

from kernel import Context, boot
from extensions.platform.loops import FakeLoop
from extensions.platform.loops.hermes import HermesLoop
from extensions.platform.render import ArtifactRenderer, RenderPlugin
from extensions.platform.session import SessionPlugin
from extensions.platform.session.artifacts import list_artifacts, read_artifact
from extensions.business.writer import WriterPlugin
from extensions.business.writer.knowledge import WritingKnowledgeProvider
from extensions.business.writer.render import TEMPLATE_STYLE
from extensions.business.writer.task import OUTLINE_REPLY

sys.path.insert(0, HERMES_AGENT_SRC)  # 业务导入后再注入 hermes 源码路径

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


# 覆盖表格/粗体/多级标题的确定性合并稿
MERGE_MD = """## 合并稿

### 第一章 编制依据
本方案依据 **JTG F90-2015** 编制。

- 规范一
- 规范二

| 序号 | 规范名称 | 编号 |
|------|---------|------|
| 1 | 公路工程施工安全技术规范 | JTG F90-2015 |
"""

FAKE_REPLIES = {
    "总结": "项目概况摘要 (fake)",
    "大纲": OUTLINE_REPLY,
    "编制依据": "# 一、编制依据\nfake 内容",
    "工程概况": "# 二、工程概况\nfake 内容",
    "合并": MERGE_MD,
}


def main() -> int:
    skip_real = "--skip-real" in sys.argv
    print("=" * 64)
    print("M3 验证: docx 渲染扩展点 + 模板/范例知识注入"
          + ("（跳过真实引擎）" if skip_real else ""))
    print("=" * 64)

    app = Context()
    fake = FakeLoop(name="fake-m3", replies=FAKE_REPLIES)
    app.register("agentLoop", fake)
    mounts = boot(app, [RenderPlugin(), SessionPlugin(), WriterPlugin()])
    order = [m.plugin.__class__.__name__ for m in mounts]
    print(f"\n[1] 渲染注册表: {order}")
    check("inject 推导: 渲染/会话先于 WriterPlugin",
          order == ["RenderPlugin", "SessionPlugin", "WriterPlugin"], str(order))
    renderers = app.get("renderers")
    check("ctx.renderers 已注册", renderers is not None)
    docx_renderer = renderers.get("docx")
    check("DocxRenderer 已注册（WriterPlugin 挂载时注册）", docx_renderer is not None)
    check("ArtifactRenderer 协议合规", isinstance(docx_renderer, ArtifactRenderer),
          type(docx_renderer).__name__)

    print("\n[2] md→docx 转换（构造合并稿, 确定性）")
    sessions = app.get("sessions")
    session = sessions.create_session({"project": "渲染验证"})
    filename = docx_renderer.render(session, merged=MERGE_MD,
                                    outline="# 施工方案", version=99)
    docx_path = os.path.join(session.dir, "output", filename)
    check("docx 产物生成", os.path.exists(docx_path), docx_path)

    doc = DocxDocument(docx_path)
    headings = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
    check("标题层级: Heading2×1 + Heading3×1",
          sum(1 for p in headings if p.style.name == "Heading 2") == 1
          and sum(1 for p in headings if p.style.name == "Heading 3") == 1,
          str([p.style.name for p in headings]))
    bold_runs = [r for p in doc.paragraphs for r in p.runs if r.bold]
    check("粗体 **JTG F90-2015** 解析为 bold run",
          any("JTG F90-2015" in r.text for r in bold_runs))
    bullets = [p for p in doc.paragraphs if p.style.name == "List Bullet"]
    check("列表项 ×2", len(bullets) == 2, str(len(bullets)))
    check("表格 2 行 × 3 列（含表头）",
          len(doc.tables) == 1 and len(doc.tables[0].rows) == 2
          and len(doc.tables[0].columns) == 3)
    check("表头加粗", doc.tables[0].cell(0, 0).paragraphs[0].runs[0].bold is True)
    check("页眉 = 施工方案", doc.sections[0].header.paragraphs[0].text == "施工方案")

    print("\n[3] 模板样式生效")
    h1 = [p for p in doc.paragraphs if p.style.name == "Heading 1"][0]
    run = h1.runs[0]
    s = TEMPLATE_STYLE["h1"]
    check("H1 字号 = 模板定义", run.font.size.pt == s["size"], f"{run.font.size.pt}pt")
    check("H1 颜色 = 模板定义",
          run.font.color.rgb == RGBColor(*s["color"]), str(run.font.color.rgb))

    print("\n[4] 知识注入（模板/范例）")
    provider = app.get("knowledge")
    check("KnowledgeProvider 注册", isinstance(provider, WritingKnowledgeProvider))
    scope = provider.scope("writer-plan", {"project_type": "tunnel"})
    check("scope 返回模板+范例目录", len(scope) == 2, str(scope))
    check("模板资源存在",
          os.path.exists(os.path.join(scope[0], "方案模板.md")), scope[0])
    check("范例资源存在",
          os.path.exists(os.path.join(scope[1], "隧道施工方案示例.md")), scope[1])

    print("\n[5] pipeline 集成（FakeLoop）")
    pipeline = app.get("writerPipeline")
    session2 = sessions.create_session({"project": "流水线渲染验证"})
    result = pipeline.run(session2, "流水线渲染验证", chapters=["编制依据", "工程概况"])
    outputs = list_artifacts(session2.dir, "output")
    check("双产物: 方案_v1.md + 方案_v1.docx",
          "方案_v1.md" in outputs and "方案_v1.docx" in outputs, str(outputs))
    check("docx 可读回（标题存在）",
          len([p for p in DocxDocument(
              os.path.join(session2.dir, "output", "方案_v1.docx")).paragraphs
              if p.style.name.startswith("Heading")]) > 0)

    print("\n[6] 真实引擎模板抽验（1 次 API）")
    if skip_real:
        print("  ⏭  --skip-real, 跳过")
    else:
        llm = _load_llm_config()
        loop = HermesLoop(ctx=app, model=llm["LLM_MODEL"], api_key=llm["LLM_API_KEY"],
                          base_url=llm["LLM_BASE_URL"])
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "biz", "writer", "resources", "templates", "方案模板.md"),
                  encoding="utf-8") as f:
            template = f.read()
        resp = loop.run_conversation(
            f"请按以下章节模板生成施工方案大纲（只输出大纲）:\n\n{template}",
            system_prompt="你是施工方案编写助手。", toolsets=[],
        )["final_response"]
        required = ("编制依据" in resp and "工程概况" in resp
                    and "应急预案" in resp)
        check("输出遵循模板章节结构（编制依据/工程概况/应急预案）",
              required, resp[:80].replace("\n", " ") + "…")

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print(f"✅ M3 全部通过 — 渲染扩展点 + docx 渲染 + 知识注入"
              + ("（真实引擎未跑）" if skip_real else ""))
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
