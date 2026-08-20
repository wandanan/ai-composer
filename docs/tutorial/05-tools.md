# 05 - 工具链

本教程的目标：掌握 `aic` 六命令——它们共享同一套声明式元数据，构成完整的工程闭环：

```
init（装）→ graph（看）→ caps（查）→ promote（升）→ uninstall（卸）
                                    └→ template（模板）
```

## 命令总览

| 命令 | 动作 | 默认行为 |
|---|---|---|
| `aic init <name>` | 创建新应用（壳 + 插件骨架） | 生成 9 文件 |
| `aic graph` | 生成项目结构图谱 | 输出 graph-viz.html（自包含，双击即开） |
| `aic caps` | 显示框架可用能力（平台服务/业务插件/声明工具/引擎） | 写能力前先查——四问判断源在声明层, 不用读源码 |
| `aic skills` | 覆盖更新项目根三平台开发 Skill | 安装新版本后同步 aic-paradigm（init 是幂等复制, 这是覆盖更新） |
| `aic promote <类> [--yes]` | 私有插件上浮为公共插件 | 默认预演：只显示影响清单，加 `--yes` 执行 |
| `aic uninstall <应用> [--yes]` | 卸载应用/插件 | 默认预演：只显示影响清单，加 `--yes` 执行 |
| `aic template <应用> [--out]` | 提取新应用开发模板 | 提取到 aic-template/（`--dry-run` 预演） |

仓库开发模式等价命令：`python -m aic.tools.cli <命令>`（或 `python -m aic.tools.<命令>`）。
所有工具支持 `KIT_PROJECT_ROOT` 环境变量指定项目根（测试用）。
完整的命令速查与开发规范见项目 Skill（`.claude/skills/aic-paradigm/`）。

## init：装

```bash
aic init my_app
```

生成壳（6 文件 + config/）+ 业务插件骨架（plugin.py + __init__.py）。`tasks.py`/`worker.py` 是**空档位**——可以不用但必须要有（壳布局契约要求装配组齐全）。

## graph：看

```bash
aic graph
start graph-viz.html     # Windows; macOS/Linux 用 open
```

图谱把声明式元数据（`inject`/`provides`/`PLUGINS`）可视化成三重视图：

```
力导向图    节点大小 ∝ 引用数; 边 = 挂载/依赖/提供
代码树      左侧面板: 应用 → 插件 → 归属分组（可折叠）
弹窗        点击插件: AI 判定 / 被应用数 / 方法 / 依赖与提供的 key
```

交互：按应用过滤、按类别过滤（平台/领域/孤儿/动态/AI）、树与图双向联动。**孤儿插件（无应用挂载）在图上以虚线显示**——一目了然哪些是残留。

## caps：查

```bash
aic caps
```

显示框架现在有什么可用——四问判断源全部落声明层（不用读源码）：

```
语义（是不是这功能?）  → 服务 key + 特性说明
形状（代码能不能跑?）  → 协议/服务形状（provides + 插件名）
实现（内部件合不合适?）→ 换法（构造参数: impl/redis_url/runtime_dir...）
行为（需要增强吗?）    → 特性说明（插件 docstring 首行）
```

输出四段：

```
== 平台服务 ==   key + 插件 + 换法 + 特性  → ctx.get(key) 直接消费
== 业务插件 ==   插件 + provides + 特性     → profile.py 挂载
== 声明工具 ==   UTILITY_MODULES 白名单     → 纯函数直接 import
== 引擎 ==       agentLoop 实现选择        → shell 引擎决策 / profile.py 可换
```

**能力阶梯**（写任何能力前先爬）：平台服务 → 业务插件 → 声明工具 → 部分满足则扩展（注入/包装/覆盖）→ 都没有才写新插件。

## promote：升（私有 → 公共）

**上浮 = 生命周期解绑**：插件从"随应用删除"变为"独立生命周期"。

```bash
aic promote StandardPlugin           # 预演: 显示移动/引用更新/标记位置
aic promote StandardPlugin --yes     # 执行: 移动包 + 更新全项目 import + 写 PUBLIC 标记
```

上浮后：

- 该插件**不随任何应用卸载删除**（`uninstall` 自动识别 PUBLIC 标记）
- 只能单独卸载：`aic uninstall --plugin StandardPlugin --yes`（无挂载/消费方时）

## uninstall：卸

```bash
aic uninstall my_app                 # 预演: 显示删除/保留清单
aic uninstall my_app --yes           # 执行
```

影响分析规则：

```
应用卸载:  删除 = 壳 + 专属插件（只挂载该应用且非公共）
           保留 = 共享插件 / 公共插件（独立生命周期）/ 动态插件
插件卸载:  有挂载应用或消费方 → 拒绝并列出; 无 → 删除插件包
```

卸载后自动验证剩余应用——卸载不能伤及他人。

## template：模板（跨应用复用）

```bash
aic template review --dry-run         # 预演: 只显示清单（公共插件 + 未上浮提示）
aic template review --out ~/my-tpl    # 提取
```

模板只带走**公共插件**（PUBLIC 标记，上浮过 = 你显式声明的传承）：

```
模板 = 基础 AIC（kernel/tools/引擎）+ 公共插件 + 示例壳 hello_aic
     + docs/learn + 自动生成的 requirements.txt（按模板实际 import 过滤）
```

**这是范式的核心用法**：新项目从"已验证的公共插件"起步，而不是空白骨架。想把什么带进模板——先 `aic promote` 它。

## 生命周期全景

```
私有插件    生命周期 = 应用        卸载应用 → 随删
公共插件    生命周期 = 独立        卸载应用 → 保留; 只能单独卸
上浮        解绑事件              aic promote
模板        传承载体              aic template（只带走公共插件）
理想应用    无私有插件            卸载只删壳——能力全在可复用层
```

## 下一步

进入 [06 - 最佳实践](06-best-practices.md)，了解插件设计、上浮判断与架构演进。
