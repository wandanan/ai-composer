"""m4b_main.py — M4b 验证：基础设施插件化（配置/遥测/存储/缓存）。

运行: PYTHONIOENCODING=utf-8 python m4b_main.py
（全部确定性验证，无 API 成本）

验证项:
  [1] 基础设施插件装配: 与业务插件同构（boot/inject 排序）
  [2] 服务可用: config/telemetry/storage/cache 基础操作
  [3] 业务插件依赖注入: InfraConsumerPlugin inject 4 项基础设施（调用时取纪律）
  [4] 实现替换: LocalStorage → MemoryStorage, 消费方零改动
  [5] 可逆销毁: unmount 后服务撤销零残留, 不误伤其他基础设施
  [6] 真实适配器协议合规: MinioStorage/RedisCache 实现协议（strangler 阶段接真连接）
"""
from __future__ import annotations
# ── 路径引导: 脚本位于 test/ 下, 确保项目根在 sys.path ──
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import os
import tempfile

from kernel import Context, Plugin, ServiceNotFound, boot
from extensions.platform.base import CachePlugin, ConfigPlugin, StoragePlugin, TelemetryPlugin
from extensions.platform.base.cache import Cache, RedisCache
from extensions.platform.base.storage import LocalStorage, MemoryStorage, MinioStorage, ObjectStorage

_PASS: list[bool] = []


def _rejects(key: str) -> bool:
    try:
        LocalStorage().put(key, b"x")
        return False
    except ValueError:
        return True


def check(name: str, ok: bool, detail: str = "") -> None:
    _PASS.append(ok)
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


class InfraConsumerPlugin(Plugin):
    """演示业务插件：依赖 4 项基础设施（调用时取纪律, 不缓存引用）。"""

    inject = ["config", "telemetry", "storage", "cache"]
    provides = ["infraDemo"]

    def apply(self, ctx: Context):
        def _demo() -> dict:
            # 调用时取 —— [4] 替换验证的前提
            cfg = ctx.get("config")
            storage = ctx.get("storage")
            cache = ctx.get("cache")
            telemetry = ctx.get("telemetry")
            model = cfg.get("llm", "LLM_MODEL", "unknown")
            cache.set("k", "v")
            storage.put("artifacts/demo.txt", b"hello")
            telemetry.trace("infra/demo", model=model, cached=cache.get("k"))
            return {
                "model": model,
                "exists": storage.exists("artifacts/demo.txt"),
                "storage_type": type(storage).__name__,
                "cached": cache.get("k"),
            }
        ctx.register("infraDemo", _demo)


def main() -> int:
    print("=" * 64)
    print("M4b 验证: 基础设施插件化（配置/遥测/存储/缓存）")
    print("=" * 64)

    # 测试配置
    tmp = tempfile.mkdtemp(prefix="m4b_")
    ini_path = os.path.join(tmp, "config.local.ini")
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write("[llm]\nLLM_MODEL=test-model\n")

    app = Context()
    mounts = boot(app, [
        ConfigPlugin(path=ini_path),
        TelemetryPlugin(),
        StoragePlugin(),
        CachePlugin(),
        InfraConsumerPlugin(),
    ])
    order = [m.plugin.__class__.__name__ for m in mounts]
    print(f"\n[1] 装配: {order}")
    check("基础设施插件与业务插件同构装配",
          order == ["ConfigPlugin", "TelemetryPlugin", "StoragePlugin",
                    "CachePlugin", "InfraConsumerPlugin"], str(order))

    print("\n[2] 服务可用")
    check("config.get 读 INI", app.get("config").get("llm", "LLM_MODEL") == "test-model")
    storage = app.get("storage")
    storage.put("x/y.txt", b"data")
    check("storage put/get 往返", storage.get("x/y.txt") == b"data")
    cache = app.get("cache")
    cache.set("key", "val", ttl=60)
    check("cache set/get", cache.get("key") == "val")
    cache.set("expired", "v", ttl=-1)
    check("cache TTL 过期", cache.get("expired") is None)

    print("\n[3] 业务插件依赖注入（调用时取纪律）")
    demo = app.get("infraDemo")
    result = demo()
    check("注入可用: 配置/存储/缓存/遥测全链路",
          result["model"] == "test-model" and result["exists"]
          and result["storage_type"] == "LocalStorage"
          and result["cached"] == "v", str(result))

    print("\n[4] 实现替换（LocalStorage → MemoryStorage, 消费方零改动）")
    replaced_disposer = app.register("storage", MemoryStorage())  # 换实现 = 重新注册
    result2 = demo()
    check("消费方零改动拿到新实现", result2["storage_type"] == "MemoryStorage",
          result2["storage_type"])
    check("新实现正常服务（数据写入内存存储）", result2["exists"] and result2["cached"] == "v")

    print("\n[5] 可逆销毁（unmount 零残留, 不误伤）")
    app.unmount(mounts[2])   # 卸载 StoragePlugin（第 3 个）
    still = app.get("storage")
    check("卸载 StoragePlugin 后: 替换的 MemoryStorage 仍在（dispose 守卫不误删他人覆盖）",
          isinstance(still, MemoryStorage), type(still).__name__)
    check("其他基础设施未误伤（config/telemetry/cache 仍在）",
          app.has("config") and app.has("telemetry") and app.has("cache"))
    replaced_disposer()      # 撤销 [4] 的替换注册
    try:
        app.get("storage")
        storage_gone = False
    except ServiceNotFound:
        storage_gone = True
    check("撤销替换注册后 ctx.storage 才消失（零残留）", storage_gone)
    app.unmount(mounts[4])
    try:
        app.get("infraDemo")
        demo_gone = False
    except ServiceNotFound:
        demo_gone = True
    check("卸载 InfraConsumerPlugin 后服务撤销", demo_gone)

    print("\n[6] 真实适配器协议合规（strangler 阶段接真连接）")
    check("MinioStorage 实现 ObjectStorage 协议",
          isinstance(MinioStorage(endpoint="http://localhost:9000"), ObjectStorage))
    check("RedisCache 实现 Cache 协议",
          isinstance(RedisCache(host="127.0.0.1"), Cache))

    print("\n[7] storage key 契约校验（/ 分层, 禁 : \\ .. 绝对路径）")
    bad_keys = ["a:b", "a\\b", "../escape", "a//b", "/abs", "C:drive", "a b", ""]
    ok_bad = all(_rejects(key) for key in bad_keys)
    check("非法 key 全部被拒（冒号/反斜杠/穿越/绝对路径/空格/空串）", ok_bad)
    good = LocalStorage()
    good.put("todo/abc123/meta", b"x")
    good.get("todo/abc123/meta")
    check("合规 key（/ 分层）可读写", good.exists("todo/abc123/meta"))

    print("\n" + "=" * 64)
    failed = _PASS.count(False)
    if failed == 0:
        print("✅ M4b 全部通过 — 基础设施可插件化（同构/注入/替换/可逆）")
    else:
        print(f"❌ {failed} 项失败")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
