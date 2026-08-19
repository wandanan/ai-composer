"""tools/graph.py — 项目结构图谱（生成自包含交互 HTML）。

数据来自声明式元数据（AST 静态扫描, 不运行任何装配）:
  - apps/<app>/profile.py 的 PLUGINS 列表      → 应用挂载哪些插件
  - apps/<app>/shell.py 的条件追加             → 动态插件（壳按环境变量挂载）
  - extensions/**/ 的 Plugin 子类 inject/provides → 插件依赖/提供哪些协议 key

图模型（key 是中间节点, 依赖语义精确可读）:
  应用 ──mount──▶ 插件 ──inject──▶ key ◀──provides── 插件

用法:
    python -m tools.graph        # 生成 graph-viz.html（双击打开）

交互都在网页上按需使用（点击插件高亮引用闭包 = 卸载影响, 查看挂载应用/
依赖/提供; 悬停详情; 拖拽缩放）。孤儿 = 无应用挂载的插件（灰色虚线）。
卸载命令（未来的元命令）自包含计算影响, 不依赖本命令产物。
"""
from __future__ import annotations

import ast
import json
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _root() -> str:
    """项目根 = 当前工作目录（aic 是全局命令, 作用于 cwd 的项目;
    仓库开发模式 cwd 即仓库根, 行为一致）。KIT_PROJECT_ROOT 可覆盖（测试用）。"""
    return os.environ.get("KIT_PROJECT_ROOT") or os.getcwd()

# 地基: 不作为图谱扫描目标（kernel/apps 是壳, tools 是工具; extensions 是插件区惯例位）
_IGNORED_PKG = ("__pycache__",)


# ── 数据层: AST 静态扫描 ─────────────────────────────

def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _function_returns(tree: ast.AST) -> dict[str, set[str]]:
    """模块内函数 → 其 return 语句中的 Call 类名集合（函数包装插件, 如 _cache_plugin → {CachePlugin}）。"""
    factories: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            names = {sub.value.func.id for sub in ast.walk(node)
                     if isinstance(sub, ast.Return)
                     and isinstance(sub.value, ast.Call)
                     and isinstance(sub.value.func, ast.Name)}
            if names:
                factories[node.name] = names
    return factories


def _scan_profile(app_dir: str) -> tuple[dict[str, str], list[str]]:
    """解析 apps/<app>/profile.py: 返回 (imports 名字→模块, 挂载插件类名列表)。

    PLUGINS 元素若是模块内函数（如 _cache_plugin 按环境切换实现）,
    展开为其 return 的实际插件类。
    """
    tree = ast.parse(_read(os.path.join(app_dir, "profile.py")))
    imports: dict[str, str] = {}
    plugins: list[str] = []
    factories = _function_returns(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom):
            base = (node.module + ".") if node.module else ""
            for a in node.names:
                imports[a.asname or a.name] = base + a.name
        elif isinstance(node, ast.Assign):
            if not any(isinstance(t, ast.Name) and t.id == "PLUGINS"
                       for t in node.targets):
                continue
            if not isinstance(node.value, ast.List):
                continue
            for elt in node.value.elts:
                if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                    name = elt.func.id
                    if name in factories:
                        plugins.extend(sorted(factories[name]))
                    else:
                        plugins.append(name)
    return imports, plugins


def _scan_dynamic(shell_path: str) -> list[str]:
    """扫描 shell.py 中 `plugins = PLUGINS + [Xxx()]` 的条件追加 → 动态插件类名。"""
    if not os.path.exists(shell_path):
        return []
    tree = ast.parse(_read(shell_path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not (isinstance(t, ast.Name) and t.id == "plugins"):
                    continue
                v = node.value
                if isinstance(v, ast.BinOp) and isinstance(v.right, ast.List):
                    for elt in v.right.elts:
                        if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                            found.append(elt.func.id)
    return found


def _is_plugin_class(node: ast.ClassDef) -> bool:
    """类名末段为 Plugin（Plugin / kernel.Plugin / xxx.Plugin）。"""
    for b in node.bases:
        name = getattr(b, "id", None) or getattr(b, "attr", None)
        if isinstance(name, str) and name == "Plugin":
            return True
    return False


def _class_methods(node: ast.ClassDef) -> list[str]:
    """类内定义的方法名（AgentTask 形状判定的依据, 含 apply）。"""
    return [item.name for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _class_public(node: ast.ClassDef) -> bool:
    """类内 PUBLIC = True 标记（公共插件: 不随应用卸载删除, tools.promote 写入）。"""
    for item in node.body:
        if isinstance(item, ast.Assign) and len(item.targets) == 1 \
                and isinstance(item.targets[0], ast.Name) \
                and item.targets[0].id == "PUBLIC" \
                and isinstance(item.value, ast.Constant) \
                and item.value.value is True:
            return True
    return False


def _class_lists(node: ast.ClassDef) -> tuple[list[str], list[str]]:
    """提取类体内 inject/provides 列表字面量（兼容 Assign 与带注解的 AnnAssign）。"""
    inject: list[str] = []
    provides: list[str] = []
    for item in node.body:
        target = None
        if isinstance(item, ast.Assign) and len(item.targets) == 1 \
                and isinstance(item.targets[0], ast.Name):
            target = item.targets[0].id
        elif isinstance(item, ast.AnnAssign) \
                and isinstance(item.target, ast.Name):
            target = item.target.id
        if target not in ("inject", "provides") or not isinstance(item.value, ast.List):
            continue
        vals = [e.value for e in item.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if target == "inject":
            inject = vals
        else:
            provides = vals
    return inject, provides


def _scan_plugins(ext_dir: str) -> dict[str, dict]:
    """扫描插件区（extensions/）所有 Plugin 子类 → 类名 → {module, inject, provides}。

    两遍扫描: 先收集全部文件 + AgentTask 形状包（包级 AI 判定需要全量信息,
    单遍遍历时 plugin.py 可能先于 task.py 被处理）。
    """
    pkg_name = os.path.basename(os.path.abspath(ext_dir))   # "extensions"
    agenttask_pkgs: set[str] = set()   # 包含 AgentTask 形状类（build_system_prompt）的包
    entries: list[tuple[str, str, ast.AST]] = []   # (path, module, tree)
    for root, dirs, files in os.walk(ext_dir):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORED_PKG)
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, ext_dir)   # 以插件区自身为基准（同盘, 无跨盘问题）
            if f == "__init__.py":
                module = pkg_name + "." + os.path.relpath(root, ext_dir).replace(os.sep, ".")
            else:
                module = pkg_name + "." + rel[:-3].replace(os.sep, ".")
            try:
                tree = ast.parse(_read(path))
            except (OSError, SyntaxError):
                continue
            entries.append((path, module, tree))
            if any("build_system_prompt" in _class_methods(node)
                   for node in ast.walk(tree)
                   if isinstance(node, ast.ClassDef)):
                agenttask_pkgs.add(os.path.dirname(path))

    result: dict[str, dict] = {}
    for path, module, tree in entries:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_plugin_class(node):
                inject, provides = _class_lists(node)
                methods = _class_methods(node)
                result[node.name] = {
                    "module": module,
                    "inject": inject,
                    "provides": provides,
                    "methods": methods,
                    "public": _class_public(node),
                    # AI 插件 = 依赖 agentLoop（引擎驱动）或实现 AgentTask 形状
                    # （build_system_prompt 等四方法, kernel/protocols.py）
                    # 或所在包含 AgentTask 类（AI 能力常在 task.py, 不在插件类自身）
                    "ai": "agentLoop" in inject
                          or "build_system_prompt" in methods
                          or os.path.dirname(path) in agenttask_pkgs,
                }
    return result


# ── 图构建 ──────────────────────────────────────────

def build_graph() -> dict:
    """构建仓库级图谱: {apps, plugins, keys, edges}。"""
    root = _root()
    apps_dir = os.path.join(root, "apps")
    ext_dir = os.path.join(root, "extensions")
    if not os.path.isdir(apps_dir):
        raise SystemExit(f"❌ 当前目录不是 aic 项目（未找到 apps/）: {root}")
    plugins = _scan_plugins(ext_dir)

    app_mounts: dict[str, list[str]] = {}   # app → [插件类名]
    app_dynamic: dict[str, list[str]] = {}
    for name in sorted(os.listdir(apps_dir)):
        app_dir = os.path.join(apps_dir, name)
        if not os.path.isdir(app_dir) or not os.path.exists(
                os.path.join(app_dir, "profile.py")):
            continue
        _, classes = _scan_profile(app_dir)
        app_mounts[name] = classes
        app_dynamic[name] = _scan_dynamic(os.path.join(app_dir, "shell.py"))

    # 插件归属: 挂载它的应用 + 是否动态
    for cls, info in plugins.items():
        info["apps"] = sorted(a for a, cs in app_mounts.items() if cls in cs)
        info["dynamic"] = any(cls in cs for cs in app_dynamic.values())

    # 度数: 被挂载应用数 + 被依赖插件数（其他插件 inject 了它 provides 的 key）
    for cls, info in plugins.items():
        deps = [other for other, oi in plugins.items()
                if other != cls and set(info["provides"]) & set(oi["inject"])]
        info["ref_count"] = len(info["apps"]) + len(deps)

    keys = sorted({k for i in plugins.values()
                   for k in i["inject"] + i["provides"]})

    edges: list[dict] = []
    # 挂载边只保留"实现存在"的插件（空白项目 init 后平台插件实现可能缺失——
    # 标准起点是 template 模板; 缺失挂载不渲染, 避免图谱/工具崩溃）
    for app, classes in app_mounts.items():
        for cls in classes:
            if cls in plugins:
                edges.append({"from": app, "kind": "mount", "to": cls})
    for app, classes in app_dynamic.items():
        for cls in classes:
            if cls in plugins:
                edges.append({"from": app, "kind": "mount", "to": cls,
                              "dynamic": True})
    for cls, info in plugins.items():
        for k in info["inject"]:
            edges.append({"from": cls, "kind": "inject", "to": k})
        for k in info["provides"]:
            edges.append({"from": cls, "kind": "provides", "to": k})

    return {
        "apps": sorted(app_mounts),
        "plugins": plugins,
        "keys": keys,
        "edges": edges,
    }


# ── HTML 可视化（内联 D3, 自包含）────────────────────

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>AIComposer 插件关系图谱</title>
<style>
  body { margin: 0; font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
         background: #0f172a; color: #e2e8f0; overflow: hidden; }
  #info { position: fixed; left: 12px; top: 12px; z-index: 10;
          background: rgba(15,23,42,.85); border: 1px solid #334155;
          border-radius: 8px; padding: 10px 14px; font-size: 12px; max-width: 320px; }
  #info b { color: #93c5fd; }
  #legend { position: fixed; right: 12px; top: 12px; z-index: 10;
            background: rgba(15,23,42,.85); border: 1px solid #334155;
            border-radius: 8px; padding: 8px 12px; font-size: 12px; }
  .lg { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  #tree { position: fixed; left: 0; top: 0; bottom: 0; width: 320px; overflow: auto;
          background: #0b1220; border-right: 1px solid #334155;
          padding: 10px 8px; font-size: 12px; z-index: 5; }
  #tree .t-title { font-weight: 600; color: #93c5fd; margin: 4px 2px 8px; }
  #tree details { margin-left: 10px; }
  #tree summary { cursor: pointer; padding: 2px 4px; border-radius: 4px; color: #cbd5e1; }
  #tree summary:hover { background: #1e293b; }
  #tree .t-node { cursor: pointer; padding: 2px 4px; border-radius: 4px; }
  #tree .t-node:hover { background: #1e293b; }
  #tree .t-node.active { background: #1d4ed8; color: #fff; }
  #tree .t-plugin { color: #93c5fd; }
  svg { margin-left: 320px; width: calc(100vw - 320px); height: 100vh; display: block; }
  .link { stroke: #475569; stroke-opacity: .5; }
  .link.mount { stroke: #22c55e; }
  .link.inject { stroke: #f59e0b; }
  .link.provides { stroke: #38bdf8; }
  .link.fade { stroke-opacity: .04; }
  .node text { font-size: 10px; fill: #cbd5e1; pointer-events: none; }
  .node.fade { opacity: .08; }
  .node.orphan { stroke: #64748b; stroke-dasharray: 4 3; }
  .node.highlight { stroke: #f8fafc; stroke-width: 2.5; }
</style>
</head>
<body>
<div id="tree"></div>
<div id="info" style="left: 332px;">
  <b>AIComposer 插件关系图谱</b><br>
  节点大小 ∝ 引用数 · 点击插件高亮引用路径 · 点击应用按应用查看 · 拖拽/滚轮缩放<br>
  绿=应用 蓝=插件 灰=协议 key 虚线=孤儿 黄线=依赖 蓝线=提供
  <div id="appfilter" style="margin-top:6px;">按应用查看
    <select id="appSel" style="background:#1e293b;color:#e2e8f0;
            border:1px solid #334155;border-radius:4px;padding:2px 6px;"></select>
  </div>
  <div id="kindfilter" style="margin-top:4px;">插件类别
    <select id="kindSel" style="background:#1e293b;color:#e2e8f0;
            border:1px solid #334155;border-radius:4px;padding:2px 6px;">
      <option value="all">全部</option>
      <option value="platform">🌐 平台（多应用共享）</option>
      <option value="domain">🧩 领域（单应用）</option>
      <option value="orphan">🚫 孤儿</option>
      <option value="dynamic">⚡ 动态</option>
      <option value="ai">🤖 AI 插件</option>
    </select>
  </div>
  <div id="detail" style="margin-top:6px; color:#94a3b8;"></div>
</div>
<svg id="g"></svg>
<script>
/*__D3_INLINE__*/
</script>
<script>
const GRAPH = __GRAPH_JSON__;
const COLORS = { app: "#22c55e", plugin: "#4f8cff", key: "#94a3b8" };

const nodes = [], links = [];
const byName = {};
for (const app of GRAPH.apps) {
  const n = { id: app, kind: "app", r: 10 }; nodes.push(n); byName[app] = n;
}
for (const [name, info] of Object.entries(GRAPH.plugins)) {
  const n = { id: name, kind: "plugin", r: 8 + Math.sqrt(info.ref_count) * 6,
              orphan: info.apps.length === 0 && !info.dynamic, info };
  nodes.push(n); byName[name] = n;
}
for (const k of GRAPH.keys) { const n = { id: k, kind: "key", r: 5 };
  nodes.push(n); byName[k] = n; }
for (const e of GRAPH.edges) {
  links.push({ source: byName[e.from], target: byName[e.to], kind: e.kind });
}

const svg = d3.select("#g");
const view = svg.append("g");
svg.call(d3.zoom().scaleExtent([.2, 6]).on("zoom", ev => view.attr("transform", ev.transform)));

const link = view.append("g").selectAll("line").data(links).join("line")
  .attr("class", d => "link " + d.kind);

const node = view.append("g").selectAll("g").data(nodes).join("g")
  .attr("class", d => "node" + (d.orphan ? " orphan" : ""))
  .call(d3.drag().on("start", dragstart).on("drag", dragged).on("end", dragend));

node.append("circle").attr("r", d => d.r).attr("fill", d => COLORS[d.kind]);
node.append("text").attr("x", d => d.r + 4).attr("y", 3).text(d => d.id);

const sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).distance(90).strength(.5))
  .force("charge", d3.forceManyBody().strength(-260))
  .force("center", d3.forceCenter(window.innerWidth / 2, window.innerHeight / 2))
  .force("collide", d3.forceCollide().radius(d => d.r + 14));

sim.on("tick", () => {
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${d.x},${d.y})`);
});

// ── 按应用查看: 过滤到该应用的插件子图 ────────────────
const appSel = d3.select("#appSel");
GRAPH.apps.forEach(a => appSel.append("option").attr("value", a).text(a));

function _applyVisible(visible) {
  node.attr("display", d => visible.has(d.id) ? null : "none");
  link.attr("display", l => visible.has(l.source.id) && visible.has(l.target.id)
                            ? null : "none");
  node.classed("fade", false).classed("highlight", false);
  link.classed("fade", false);
  d3.select("#detail").html("");
  if (treeEl) treeEl.querySelectorAll(".t-plugin").forEach(el => el.classList.remove("active"));
  sim.nodes(nodes.filter(n => visible.has(n.id)));
  sim.force("link").links(links.filter(l => visible.has(l.source.id)
                                           && visible.has(l.target.id)));
  sim.alpha(.8).restart();
}

function applyAppFilter(app) {
  kindSel.property("value", "all");   // 互斥: 应用过滤重置类别过滤
  const visible = new Set();
  if (app !== "all") {
    visible.add(app);
    for (const e of GRAPH.edges) {
      if (e.kind === "mount" && e.from === app) {
        visible.add(e.to);                    // 挂载的插件
        const info = GRAPH.plugins[e.to];
        if (info) {
          info.inject.forEach(k => visible.add(k));     // 依赖的 key
          info.provides.forEach(k => visible.add(k));   // 提供的 key
        }
      }
    }
    for (const [cls, info] of Object.entries(GRAPH.plugins)) {
      if (info.provides.some(k => visible.has(k))) visible.add(cls);  // key 的提供者
    }
  } else {
    nodes.forEach(n => visible.add(n.id));
  }
  _applyVisible(visible);
}

function applyKindFilter(kind) {
  appSel.property("value", "all");   // 互斥: 类别过滤重置应用过滤
  const visible = new Set();
  if (kind !== "all") {
    for (const [cls, info] of Object.entries(GRAPH.plugins)) {
      const match = kind === "platform" ? (info.apps.length > 1 && !info.dynamic)
        : kind === "domain"   ? (info.apps.length === 1 && !info.dynamic)
        : kind === "orphan"   ? (info.apps.length === 0 && !info.dynamic)
        : kind === "dynamic"  ? info.dynamic
        : kind === "ai"       ? info.ai
        : false;
      if (match) {
        visible.add(cls);
        info.apps.forEach(a => visible.add(a));     // 挂载应用
        info.inject.forEach(k => visible.add(k));   // 依赖 key
        info.provides.forEach(k => visible.add(k)); // 提供 key
      }
    }
    for (const [cls, info] of Object.entries(GRAPH.plugins)) {
      if (info.provides.some(k => visible.has(k))) visible.add(cls);  // key 提供者补全
    }
  } else {
    nodes.forEach(n => visible.add(n.id));
  }
  _applyVisible(visible);
}

const kindSel = d3.select("#kindSel");
appSel.on("change", () => applyAppFilter(appSel.property("value")));
kindSel.on("change", () => applyKindFilter(kindSel.property("value")));

function neighbors(d) {
  const s = new Set([d.id]);
  const queue = [d];
  while (queue.length) {
    const cur = queue.shift();
    for (const l of links) {
      if (l.source.id === cur.id && !s.has(l.target.id)) { s.add(l.target.id); queue.push(l.target); }
      if (l.target.id === cur.id && !s.has(l.source.id)) { s.add(l.source.id); queue.push(l.source); }
    }
  }
  return s;
}

function showDetail(d) {
  const det = d3.select("#detail");
  if (d.kind === "plugin") {
    const apps = d.info.apps.join(", ") || (d.info.dynamic ? "动态" : "孤儿");
    const consumers = Object.entries(GRAPH.plugins)
      .filter(([c, i]) => c !== d.id && i.inject.some(k => d.info.provides.includes(k))).length;
    const ai = d.info.ai ? "🤖 AI 插件" : "纯逻辑插件";
    det.html(`<b>${d.id}</b> ${d.info.module}<br>
      ${ai} · 被应用数 ${d.info.apps.length} · 被依赖 ${consumers}
      · 引用 ${d.info.ref_count}<br>
      挂载应用: ${apps}<br>
      方法: ${d.info.methods.join(", ")}<br>
      依赖 key: ${d.info.inject.join(", ")}<br>
      提供 key: ${d.info.provides.join(", ")}`);
  } else if (d.kind === "app") {
    const ms = links.filter(l => l.kind === "mount" && l.source.id === d.id)
      .map(l => l.target.id).join(", ");
    det.html(`<b>${d.id}</b> 应用壳<br>挂载: ${ms}`);
  } else {
    const prov = links.filter(l => l.kind === "provides" && l.target.id === d.id)
      .map(l => l.source.id).join(", ");
    const cons = links.filter(l => l.kind === "inject" && l.target.id === d.id)
      .map(l => l.source.id).join(", ");
    det.html(`<b>${d.id}</b> 协议 key<br>提供: ${prov}<br>依赖: ${cons}`);
  }
}

function selectPlugin(cls) {
  if (appSel.property("value") !== "all") applyAppFilter("all");  // 树点击: 先回全图
  const d = byName[cls];
  if (!d) return;
  const hit = neighbors(d);
  node.classed("fade", n => !hit.has(n.id)).classed("highlight", n => n.id === d.id);
  link.classed("fade", l => !(hit.has(l.source.id) && hit.has(l.target.id)));
  showDetail(d);
  treeEl.querySelectorAll(".t-plugin").forEach(el =>
    el.classList.toggle("active", el.dataset.plugin === cls));
}

node.on("click", (ev, d) => {
  if (d.kind === "app") {           // 点击应用 = 按应用查看
    appSel.property("value", d.id);
    applyAppFilter(d.id);
    return;
  }
  selectPlugin(d.id);
});

// ── 树形架构视图（代码树, 与图谱双向联动）──────────────
const treeEl = d3.select("#tree").node();

function pluginLabel(cls) {
  const i = GRAPH.plugins[cls];
  return cls + (i.ai ? " 🤖" : "") + (i.apps.length ? ` [${i.apps.length}应用]` : " [孤儿]");
}

function buildTree() {
  let html = '<div class="t-title">📦 项目架构（点击节点 ↔ 图谱联动）</div>';
  // ① 按应用: 应用 → 挂载插件（平台/共享/领域/动态 标注）
  html += `<details open><summary>🖥️ 应用 (${GRAPH.apps.length})</summary>`;
  for (const app of GRAPH.apps) {
    html += `<details open><summary class="t-node t-app" data-app="${app}">📱 ${app}</summary>`;
    for (const e of GRAPH.edges) {
      if (e.kind !== "mount" || e.from !== app) continue;
      const cls = e.to;
      const i = GRAPH.plugins[cls];
      const kind = e.dynamic ? "⚡动态" : (i.apps.length > 1 ? "🌐共享" : "🧩领域");
      html += `<div class="t-node t-plugin" data-plugin="${cls}">${kind} ${pluginLabel(cls)}</div>`;
    }
    html += "</details>";
  }
  html += "</details>";
  // ② 插件区: 按归属分组（通用/领域/孤儿/动态）
  const groups = { "🌐 通用（多应用共享）": [], "🧩 领域（单应用）": [], "🚫 孤儿（无挂载）": [] };
  for (const [cls, i] of Object.entries(GRAPH.plugins)) {
    if (i.dynamic) continue;
    if (i.apps.length > 1) groups["🌐 通用（多应用共享）"].push(cls);
    else if (i.apps.length === 1) groups["🧩 领域（单应用）"].push(cls);
    else groups["🚫 孤儿（无挂载）"].push(cls);
  }
  const dyn = Object.entries(GRAPH.plugins).filter(([, i]) => i.dynamic).map(([c]) => c);
  html += `<details open><summary>🧩 插件区 (${Object.keys(GRAPH.plugins).length})</summary>`;
  for (const [g, list] of Object.entries(groups)) {
    if (!list.length) continue;
    html += `<details><summary>${g} (${list.length})</summary>`;
    for (const cls of list.sort()) {
      html += `<div class="t-node t-plugin" data-plugin="${cls}">${pluginLabel(cls)}</div>`;
    }
    html += "</details>";
  }
  if (dyn.length) {
    html += `<details><summary>⚡ 动态装配 (${dyn.length})</summary>`;
    for (const cls of dyn.sort()) {
      html += `<div class="t-node t-plugin" data-plugin="${cls}">${cls}（KIT_ENGINE 等条件）</div>`;
    }
    html += "</details>";
  }
  html += "</details>";
  treeEl.innerHTML = html;
  treeEl.querySelectorAll(".t-app").forEach(el => el.addEventListener("click", () => {
    appSel.property("value", el.dataset.app);
    applyAppFilter(el.dataset.app);
  }));
  treeEl.querySelectorAll(".t-plugin").forEach(el => el.addEventListener("click", () => {
    selectPlugin(el.dataset.plugin);
  }));
}
node.on("mouseover", (ev, d) => d3.select(ev.currentTarget).raise());
svg.on("click", ev => { if (ev.target === svg.node()) {
  appSel.property("value", "all");   // 点击空白 = 恢复全部
  applyAppFilter("all");
}});

buildTree();   // 初始化树形架构视图

function dragstart(ev, d) { if (!ev.active) sim.alphaTarget(.25).restart(); d.fx = d.x; d.fy = d.y; }
function dragged(ev, d) { d.fx = ev.x; d.fy = ev.y; }
function dragend(ev, d) { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }
</script>
</body>
</html>
"""


def _build_html(graph: dict, d3_source: str | None = None) -> str:
    """生成自包含 HTML: 内联 graph.json + d3.min.js（GRAPH script 之前加载）。"""
    d3js = d3_source or _read(os.path.join(_ASSETS_DIR, "d3.min.js"))
    html = _HTML_TEMPLATE.replace(
        "__GRAPH_JSON__", json.dumps(graph, ensure_ascii=False))
    return html.replace("/*__D3_INLINE__*/", d3js)


# ── CLI ─────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    """生成自包含交互图谱 graph-viz.html。"""
    graph = build_graph()
    out = os.path.join(_root(), "graph-viz.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(_build_html(graph))
    print(f"✅ 图谱已生成: {out}（双击打开, 点击插件查看引用/影响）")


if __name__ == "__main__":
    main()
