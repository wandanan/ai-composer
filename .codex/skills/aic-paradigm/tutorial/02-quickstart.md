# 02 - 快速开始

本教程的目标：**5 分钟内跑通一个 AIComposer 应用**，并理解它的目录结构。

## 1. 启动示例应用

安装包自带示例应用 `hello_aic`——它挂载了全部公共插件（配置、存储、缓存、队列、数据库、沙箱、SSE、文档提取），是一个开箱即用的 AI 应用地基。

```bash
uvicorn apps.hello_aic.main:app --port 8000
```

浏览器访问 `http://127.0.0.1:8000/health`：

**预期输出**：

```json
{"status": "healthy", "app": "hello_aic", "plugins": [...], "jobs_health": "?"}
```

`plugins` 列表显示已装配的插件——这就是"应用 = 插件组合"的运行时证据：**地基能力（80%）开箱即用，你只需要写业务（20%）**。

## 2. 创建你的第一个应用

```bash
aic init my_app
```

**预期输出**：

```
✅ 新应用已生成: my_app
   应用壳:  .../apps/my_app
   业务插件: .../extensions/business/my_app
```

查看生成的结构：

```bash
ls apps/my_app/
```

**预期输出**：

```
__init__.py  config/  main.py  profile.py  shell.py  tasks.py  worker.py
```

每个文件的职责：

| 文件 | 职责 |
|---|---|
| `profile.py` | **插件清单**——这个应用要挂哪些插件（组装点） |
| `shell.py` | **装配**——建背包、注册配置、启动装配 |
| `main.py` | **HTTP 入口**——端点只做"校验 → 调能力 → 返回" |
| `tasks.py` / `worker.py` | **异步任务**——空档位骨架（同步应用可以不用，但文件必须有） |
| `config/` | 应用配置（config.local.ini） |

## 3. 启动你的应用

```bash
uvicorn apps.my_app.main:app --port 8001
```

访问 `http://127.0.0.1:8001/health`，`plugins` 列表中包含 `MyAppPlugin`——你的业务插件已经挂载生效。

## 4. 概念速览：背包与三个角色

范式运行的全部秘密，是一个**背包**（Context）和**两个动作**：

```
放进去: ctx.register("storage", 实现)     ← 提供方做（装配时）
拿出来: ctx.get("storage")               ← 消费方做（任何需要时）
```

**为什么不能直接 import 实现？** 看换存储的例子：

```
今天:   StoragePlugin 内部是本地文件实现 → register("storage", FileStorage())
明天:   换 MinIO → 写 MinioStorage（同样的 put/get/exists）→ register("storage", MinioStorage())
效果:   所有消费方 get("storage").put(...) 一行不改
```

**这就是"可替换"的根源：消费方只依赖 key，不依赖实现。**

三个角色各管一摊：

```
内核      给机制（注册/取用/自动装配）——不认识业务
插件      给能力（业务/通用, 声明要什么 inject、给什么 provides）
应用壳    做组合（选插件清单 + 开入口）——不实现能力
```

核心口诀：**要能力 `get(key)`，给能力 `register(key)`，声明 `inject/provides` 让装配自动发生**。

> **注意**：壳（apps/）里不写业务逻辑。业务代码永远放在 `extensions/business/<业务>/` 的插件里——这是范式最重要的一条纪律，违反会在装配时被机制检查拦下。

## 5. 备选起点：从模板开始

上面的流程是"从零开始"（`aic init` 生成空白骨架）。**范式的推荐起步方式是先从模板开始**——
自带已验证的公共插件、示例应用与开发 Skill：

```bash
# 如果你有一个已有的 AIC 应用（如 review）, 提取它的开发模板:
aic template review --out ~/my-tpl      # ① 提取模板（基础 AIC + 公共插件 + hello_aic）
cd ~/my-tpl                             # ② 进入模板
pip install -r requirements.txt         # ③ 装依赖
python test/template_check.py           # ④ 模板自检
aic init my_biz                         # ⑤ 在模板上加你的新应用
```

对比两种起点：

```
从零开始（aic init）:   空白骨架——公共插件需自行沉淀/上浮
从模板开始（aic template）: 已验证的公共插件 + 示例 + 开发 Skill 开箱即用
```

> **注意**：模板只带走公共插件（上浮过 = 你显式声明的传承）。业务专属插件不会被复制——
> 模板是新的起点，不是旧应用的复制品。

## 6. 一次请求的全旅程（6 站）

```
curl POST /api/v1/...
  ↓ ① 壳(三件事)    main.py: 校验 + create_session + get + 返回
  ↓ ② 拼装          lifespan → build_shell → boot 自动装配
  ↓ ③ 插件接线      apply → register 能力进背包
  ↓ ④ 能力          服务类: 纯逻辑（不直接 IO）
  ↓ ⑤ 会话/产物     开作业单（session_id/meta/dir/turn）→ 结果落产物或数据通道
  ↓ ⑥ 流程/事件     emit 广播（进度可观察）
响应 {"session_id": "...", ...}
```

## 下一步

你已经有一个能跑的应用了。进入 [03 - 开发第一个业务插件](03-first-plugin.md)，给它写真正的业务。
