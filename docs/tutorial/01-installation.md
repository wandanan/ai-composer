# 01 - 安装

## 环境要求

| 依赖 | 版本 |
|---|---|
| Python | ≥ 3.11 |
| pip | 最新版 |

可选：Redis（任务队列与 SSE 跨进程推送）。**不安装也能运行**——队列默认使用线程内联降级。

## 安装方式一：pip 安装（推荐）

```bash
pip install ai-composer
```

如果你从源码仓库开发：

```bash
git clone <仓库地址> ai-composer
cd ai-composer
pip install -e .          # 开发模式安装（也可 pip install -r requirements.txt）
```

## 安装方式二：从 AIC 应用构建模板

如果你手上已有一个 AIC 范式应用（同事的项目、公司模板、或安装包自带的示例），
可以用 `aic template` 提取它的开发模板作为你的项目起点——**自带已验证的公共插件、
示例应用与开发 Skill**：

```bash
aic template <已有应用> --out ~/my-tpl    # ① 从已有应用提取模板
cd ~/my-tpl                               # ② 进入模板
pip install -r requirements.txt           # ③ 安装依赖（模板自动生成, 按实际 import 过滤）
python test/template_check.py             # ④ 模板自检（壳契约 + hello_aic 装配）
```

**两种方式的选择**：

```
方式一（pip）:  从零开始——aic init 生成空白骨架, 公共插件需自行沉淀/上浮
方式二（模板）: 从已验证起点开始——公共插件 + 示例应用 + 开发 Skill 开箱即用
                （范式的推荐起步方式: 新项目从"已验证的半成品"开始, 而非空白骨架）
```

> **注意**：模板只带走公共插件（上浮过 = 你显式声明的传承）。业务专属插件不会被复制——
> 模板是新的起点，不是旧应用的复制品。

## 验证安装

```bash
aic --help
```

**预期输出**：

```
用法: aic <命令> [参数]

命令:
  init       初始化新应用（生成壳 + 业务插件骨架 + 空档位 tasks/worker）
  graph      生成项目结构图谱 graph-viz.html（自包含交互, 双击即开）
  promote    私有插件 → 公共插件（移动包 + 更新引用 + PUBLIC 标记, 默认只显示影响清单）
  uninstall  应用/插件卸载（影响分析后删除, 默认只显示影响清单）
  template   新应用开发模板提取（只带走公共插件 + 示例壳 hello_aic）
```

> **Windows 提示**：终端输出中文乱码时（GBK 控制台），命令前加
> `PYTHONIOENCODING=utf-8`（如 `PYTHONIOENCODING=utf-8 aic init my_app`）——仅显示问题，不影响功能。

## 安装后获得什么

```
ai-composer 包（0.2.0: 只装 aic 一个顶层包, 与用户业务命名空间互不冲突）
├── aic/
│   ├── __init__.py   统一入口（import aic → Context/Plugin/boot/__version__）
│   ├── kernel/       内核机制（服务注册/事件/装配/可逆卸载）——零第三方依赖
│   ├── extensions/
│   │   └── platform/ 框架平台插件（配置/存储/缓存/队列/数据库/沙箱/SSE/文档提取…）
│   ├── apps/hello_aic/ 示例应用（挂载全部公共插件, 新项目的起点模板）
│   └── tools/        工具链（aic 命令的实现）
└── docs/             学习文档
```

## 下一步

进入 [02 - 快速开始](02-quickstart.md)，跑通第一个应用。
