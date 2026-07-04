"""静态自死锁回归守卫 (R20.27).

R20.25 在全量 suite 首跑时发现 2 个**非重入锁自死锁**生产 bug:
  1. ``get_cache()`` 持 ``_singleton_lock`` 调 ``get_enhanced_cache()`` (同锁)
  2. ``get_sw_industry_classification()`` 持 ``_sw_industry_cache_lock`` 调
     ``_cache_sw_industry_mapping()`` (同锁)

根因都是 ``threading.Lock()`` (非重入) 在同一对象/模块内被同一持锁路径再次获取。
子集测试无法发现 (需并发触发), 全量 suite 才暴露。

本测试用 AST 静态扫描 ``src/`` 全部锁, 断言**不存在**以下模式:
  方法 A 在 ``with L:`` 块内调用 ``self.B()`` (或模块级 ``B()``),
  而 B 本身也获取同一把锁 L (同一对象/模块)。

这是 R20.25 bug 类的回归守卫 —— 任何新增的非重入自死锁都会在此失败,
而不必等到生产 hang 或全量 suite 偶发触发。

扫描器设计要点 (前两版误报教训):
  - **赋值推断**: 不依赖 ``_lock`` 命名约定 —— 凡 ``= threading.Lock()`` 赋值的
    变量都识别为锁 (防止命名为 ``_mutex``/``_lk`` 时漏报)。
  - **接收者感知**: ``self.method()`` 才算同类方法调用; ``self._cache.clear()``
    (dict.clear) 不算 ``self.clear()``。否则跨对象同名调用会误报。
  - **作用域感知**: 只统计 ``with L:`` 块**内**的调用; 块外调用 (如 R20.25 修复
    后 ``get_cache`` 在持锁**前**调 ``get_enhanced_cache``) 不算。
  - **类感知**: 不同类的同名方法 (LRUCache.get / SQLiteCache.get) 锁不同, 不混淆。
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

import pytest


def _is_lock_call(value: ast.AST) -> bool:
    """表达式是否为 threading.Lock()/Lock()/RLock() 构造."""
    # threading.Lock() / threading.RLock()
    if isinstance(value, ast.Call):
        f = value.func
        name = None
        if isinstance(f, ast.Attribute):
            name = f.attr
        elif isinstance(f, ast.Name):
            name = f.id
        return name in {"Lock", "RLock"}
    return False


def _lock_name_of(ctx: ast.AST, known_locks: set[str]) -> str | None:
    """提取 with 上下文管理器的锁名.

    识别两种来源:
      1. 名字以 ``_lock`` 结尾 (本仓库通用约定)
      2. 在 ``known_locks`` 中 (由 ``= threading.Lock()`` 赋值推断, 不依赖命名)
    """
    name: str | None = None
    if isinstance(ctx, ast.Name):
        name = ctx.id
    elif isinstance(ctx, ast.Attribute):
        name = ctx.attr
    if name is None:
        return None
    if name.endswith("_lock") or name in known_locks:
        return name
    return None


def _same_target_callee(call_node: ast.Call) -> str | None:
    """仅识别同类方法调用 ``self.m()`` 或模块级裸调用 ``m()``.

    排除 ``self._cache.m()`` 等不同接收者 (避免 dict.clear 误匹配 self.clear)。
    """
    f = call_node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _scan_self_deadlocks(src_root: Path) -> list[str]:
    """扫描 src_root 下所有 .py, 返回自死锁描述列表 (空 = 干净)."""
    held_locks: dict[tuple[str | None, str], set[str]] = collections.defaultdict(set)
    calls_under_lock: dict[tuple[str | None, str], list[tuple[str, str]]] = collections.defaultdict(list)

    for py in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

        # 推断本文件的锁变量名 (= threading.Lock() / Lock() / RLock()),
        # 不依赖 ``_lock`` 命名约定, 防止漏报。
        known_locks: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and _is_lock_call(n.value):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        known_locks.add(t.id)
                    elif isinstance(t, ast.Attribute):
                        known_locks.add(t.attr)

        # 建立 parent 指针
        for n in ast.walk(tree):
            for child in ast.iter_child_nodes(n):
                child._parent = n  # type: ignore[attr-defined]

        def enc_class(node: ast.AST) -> str | None:
            p = getattr(node, "_parent", None)
            while p is not None:
                if isinstance(p, ast.ClassDef):
                    return p.name
                p = getattr(p, "_parent", None)
            return None

        def enc_locks(node: ast.AST) -> list[str]:
            locks: list[str] = []
            p = getattr(node, "_parent", None)
            while p is not None:
                if isinstance(p, ast.With):
                    for item in p.items:
                        ln = _lock_name_of(item.context_expr, known_locks)
                        if ln:
                            locks.append(ln)
                p = getattr(p, "_parent", None)
            return locks

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            cls = enc_class(node)
            fkey = (cls, node.name)
            for w in ast.walk(node):
                if isinstance(w, ast.With):
                    for item in w.items:
                        ln = _lock_name_of(item.context_expr, known_locks)
                        if ln:
                            held_locks[fkey].add(ln)
                if isinstance(w, ast.Call):
                    callee = _same_target_callee(w)
                    if callee and callee != node.name:  # 跳过纯自递归噪声
                        for ln in enc_locks(w):
                            calls_under_lock[fkey].append((callee, ln))

    deadlocks: list[str] = []
    for (cls, meth), call_list in calls_under_lock.items():
        owner = f"{cls}." if cls else ""
        for callee, lock in call_list:
            if lock in held_locks.get((cls, callee), set()):
                deadlocks.append(f"{owner}{meth}() 持 [{lock}] 调用 {owner}{callee}() 也获取 [{lock}]  ←  非重入锁自死锁")
    return deadlocks


def test_no_non_reentrant_self_deadlock_in_src():
    """断言 src/ 不存在非重入锁自死锁 (R20.25 bug 类回归守卫).

    失败时打印所有检测到的死锁路径, 指明文件/类/方法/锁名。
    修复方式: 把内部调用移出 ``with L:`` 块 (参考 R20.25 ``get_cache`` 修复),
    或改用 ``threading.RLock()`` (若重入确属必要)。
    """
    repo_root = Path(__file__).resolve().parent.parent
    src_root = repo_root / "src"
    assert src_root.is_dir(), f"src/ not found at {src_root}"

    deadlocks = _scan_self_deadlocks(src_root)
    if deadlocks:
        pytest.fail("检测到非重入锁自死锁 (R20.25 bug 类):\n  - " + "\n  - ".join(deadlocks) + "\n修复: 将内部调用移出 with-lock 块, 或改用 RLock。")


def test_r20_25_known_fixes_hold():
    """金丝雀: R20.25 修复的 2 处自死锁不应回归。

    这两个修复都把内部调用移到了持锁**之前** (双检锁模式)。若有人不小心把它们
    挪回 ``with _singleton_lock:`` / ``with _sw_industry_cache_lock:`` 块内,
    本测试 + 上面的全量扫描都会失败。
    """
    repo_root = Path(__file__).resolve().parent.parent
    enhanced = repo_root / "src" / "data" / "enhanced_cache.py"
    tushare = repo_root / "src" / "tools" / "tushare_api.py"
    assert enhanced.is_file() and tushare.is_file()

    # get_cache() 必须在 acquire _singleton_lock 之前调用 get_enhanced_cache()
    ec_src = enhanced.read_text(encoding="utf-8")
    # 定位 get_cache 函数体片段
    marker = "def get_cache() -> CacheAdapter:"
    assert marker in ec_src, "get_cache() 签名变更, 请更新本金丝雀"
    get_cache_body = ec_src.split(marker, 1)[1].split("\ndef ", 1)[0]
    # get_enhanced_cache 调用应出现在 'with _singleton_lock' 之前
    call_pos = get_cache_body.find("get_enhanced_cache()")
    with_pos = get_cache_body.find("with _singleton_lock")
    assert call_pos != -1 and with_pos != -1, "get_cache 结构变更, 请更新本金丝雀"
    assert call_pos < with_pos, "R20.25 回归: get_cache() 在持 _singleton_lock 后才调 get_enhanced_cache() → 自死锁"

    # get_sw_industry_classification 不应在持 _sw_industry_cache_lock 时调 _cache_sw_industry_mapping
    ts_src = tushare.read_text(encoding="utf-8")
    marker2 = "def get_sw_industry_classification"
    assert marker2 in ts_src, "get_sw_industry_classification 签名变更, 请更新本金丝雀"
    body2 = ts_src.split(marker2, 1)[1].split("\ndef ", 1)[0]
    cache_call = body2.find("_cache_sw_industry_mapping(")
    with_lock = body2.find("with _sw_industry_cache_lock")
    if cache_call != -1 and with_lock != -1 and cache_call > with_lock:
        pytest.fail("R20.25 回归: get_sw_industry_classification 持锁后调 _cache_sw_industry_mapping → 自死锁")
