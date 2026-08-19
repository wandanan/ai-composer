# 社区生态调研 — 插件化 Agent 框架与 Cordis

> **调研日期**: 2026-08-18 | **方式**: 联网检索（两次）| **用途**: 范式定位参照与借鉴
> **结论先行**: 方向被市场验证（dsh 爆火），差异化位置真实（通用应用范式 + Python + 不绑定 AI）；
> Cordis 生态成熟（4 年 / 4000+ 插件），"可逆效果"组合在社区中无对等物。

---

## 一、检索 1：插件化 Agent 应用框架对照（"everything is a plugin"）

### 1.1 最近发现：DeepSeek Harness（dsh）

2026-08-13 开源，半天 1 万+ stars（后达 62.9K~100K+），社区插件 1000+。

| 维度 | dsh | AIComposer |
|------|-----|-----------|
| 一切皆插件 | ✅ 模型/工具/会话/loop 全是插件 | ✅ 内核 + 插件体系 |
| 生命周期管理 | ✅ 热插拔 | ✅ mount/unmount/替换/降级 |
| 场景 | agent harness（coding agent/终端/IDE） | 业务应用开发范式（不绑定 AI） |
| 语言 | TypeScript | Python |
| 应用壳模型 | profile/bundle 组合 | apps/ 壳 + 多入口形态 |
| 不绑定 AI | ❌ | ✅（file-convert/todo 实证） |

**定位判断**: dsh 是最接近的哲学参照，但不是同类产品——它是"agent 运行时"，AIComposer 是"应用开发平台"。

### 1.2 有插件概念但维度不同的框架

| 框架 | 插件/组合形态 | 差异点 |
|------|-------------|--------|
| Semantic Kernel（微软, 已并入 Microsoft Agent Framework） | Kernel + Plugin（plugin = 可复用 AI 函数） | 插件是函数工具级，无生命周期管理/应用壳模型；绑定 AI 场景 |
| LangChain/LangGraph | 组件化 + 生态集成（281K 依赖仓库, 模型一行可换） | 是编排库非应用框架；无插件生命周期；依赖重（~100 依赖） |
| Mastra（TS） | All-in-one 包 + MCP 工具集成（~20 依赖） | 组合思想但无插件生命周期；仅 TS |
| Eliza（AI16z） | 插件体系（actions/providers/evaluators） | 本次检索无直接来源；据社区已知为 TS + 社交/crypto 场景 |

**平台型产品**（Dify/Langflow/n8n）为低代码组装，面向最终用户，非开发框架，不构成同类。

### 1.3 独特性结论

社区中"通用应用开发范式 + 生命周期管理 + 应用壳模型 + 不绑定 AI"的组合**没有完全一致的项目**：
- dsh: 一切皆插件 ✅ 但 agent harness（TS, 绑定 AI 场景）
- SK/MAF: kernel+plugin ✅ 但函数工具级, 无生命周期, 绑定 AI
- LangGraph: 组合编排 ✅ 但无插件生命周期, 库非平台
- **AIComposer: 通用应用范式 + 生命周期 + 壳模型 + Python + 不绑定 AI ← 独特**

---

## 二、检索 2：Cordis 生态与类似框架

### 2.1 Cordis 本尊

- 作者 Shigma（Koishi 创始人, 现 DeepSeek-AI）；~2,000 行核心 TS；MIT；2022-05 首提交
- 出身: 最初为 Koishi 内核, v4.7 独立为 `@cordisjs/core`（npm）
- 学术背书: 北大 + DeepSeek 论文《A Programming Paradigm for Spatiotemporal Composability》
- 核心设计: 服务/依赖注入（inject）/类型化事件（emit/waterfall/parallel/serial）/可逆效果（ctx.effect + disposer）
- 验证: Koishi 社区 4,000+ 插件, 4 年生产运行

### 2.2 Cordis 生态（基于它的项目）

| 项目 | 关系 | 说明 |
|------|------|------|
| Koishi | 最大应用 | 聊天机器人框架, 4000+ 插件市场 |
| DeepSeek Harness | vendoring 采用 | vendor/cordis 进 monorepo, 非重写 |
| @cordisjs/plugin-webui | 官方插件 | 插件树 Web UI |
| minato | 生态插件 | **数据库层作为 Cordis 插件**（DB 接入形态参考） |
| cordis-rs | 社区移植 | Rust 零依赖移植（scoped DI + 生命周期效果 + 5 事件模式） |

### 2.3 类似 Cordis 的框架：空白（组合独特）

"可逆效果（运行时级）+ 依赖注入 + 事件总线 + 插件生命周期"组合无对等物，跨语言仅 cordis-rs 一个移植。

| 生态 | 框架 | 为什么不是同类 |
|------|------|--------------|
| Python | pluggy（pytest） | 只有钩子, 无 DI/生命周期/可逆效果 |
| Java | Spring | 有 IOC/DI, 无可逆效果语义 |
| Node | NestJS / Fastify 插件 | 有 DI/模块, 无"注册即效果、卸载即撤销" |
| 概念类比 | React useEffect / C++ RAII / Rust Drop / Docker 生命周期 | 都是可逆效果思想, 但未提升到框架级插件管理 |

**空白原因**: Cordis 把"确定性清理"（RAII 思想）从语言层提升到运行时插件层——"装什么、卸载一定撤销干净、与加载顺序无关"（路径无关性）。其他框架未做。

---

## 三、对 AIComposer 的启示

1. **方向被市场验证**: dsh 的爆发（"AI 的乐高时代"）说明"插件化组合"是 2026 年 agent 开发主流叙事；AIComposer 不是小众方向
2. **差异化空间真实**: dsh 做 agent harness（终端场景），"业务系统应用开发"（审查/编写/非 AI 应用）无同类——定位独特
3. **内核有背书**: 230 行 Python 内核 = Cordis 思想的轻量实现——有学术论文、4000+ 插件生态、dsh 工业验证三重背书
4. **可借鉴**: 
   - dsh 插件生态目录模式（未来对外开放时的教材）
   - cordis-rs 零依赖实现（对照验证内核语义无遗漏）
   - minato（DB 层作插件）——strangler DB 接入的形态参考

---

## 四、来源引用

### 检索 1（插件化 Agent 框架对照）

- [DeepSeek Harness: Everything-is-a-Plugin Developer Preview (SitePoint)](https://www.sitepoint.com/deepseek-harness-developer-preview/)
- [DeepSeek's innovative harness treats everything as a plug-in (The Register)](https://www.theregister.com/ai-and-ml/2026/08/14/deepseeks-innovative-harness-treats-everything-as-a-plug-in/5288095)
- [DeepSeek Harness Plugins 指南 (OrcaRouter)](https://www.orcarouter.ai/blog/deepseek-harness-plugins)
- [The Complete Guide to AI Agent Frameworks in 2026](https://aiagenttools.dev/blog-ai-agent-frameworks-guide)
- [LangChain: The best AI agent frameworks in 2026](https://www.langchain.com/resources/ai-agent-frameworks)
- [Agent Harness Toolkit Showdown 2026 (Atlas)](https://github.com/Laoujin/Atlas/blob/main/research/2026-06-03-agent-harness-toolkit-showdown-2026/index.md)
- [Ultimate Guide to Open Source AI Agent Frameworks in 2026](https://the-agent-report.com/2026/05/ultimate-guide-open-source-ai-agent-frameworks/)
- [AI 行业资讯：DeepSeek Harness 万物皆插件（WPS）](https://bbs.wps.cn/topic/94830)

### 检索 2（Cordis 生态）

- [Cordis: 一颗被 DeepSeek Harness 选中的"插件心脏"](https://damodev.csdn.net/6a82f5b1662f9a54cb9de2af.html)
- [Cordis 框架代码核心解析：可逆插件系统](https://deepseek.csdn.net/6a7f3cde10ee7a33f29b0b28.html)
- [Koishi 4.17.0-alpha.0 讨论](https://github.com/koishijs/koishi/discussions/1361)
- [Koishi 文档：可逆插件系统设计](https://koishi.chat/fr-FR/cookbook/design/disposable.html)
- [cordis-rs（Rust 移植）](https://github.com/dshbox/cordis-rs)
- [DeepSeek Harness 论文解读：Spatiotemporal Composability](https://raw.githubusercontent.com/xiaonancs/deepseek-harness-deep-dive/main/Part%20IV%20Foundational%20Paper/22-A-Programming-Paradigm-for-Spatiotemporal-Composability.md)
- [Cordis Primer（dsh 官方文档）](https://github.com/deepseek-ai/deepseek-harness/blob/HEAD/docs/cordis-primer.md?plain=1)
