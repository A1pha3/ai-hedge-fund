"""夜链 CLI 死参数家族守卫 (R233 Op1)。

M14 定谳 (R232 Op2 探针 M14): flow_backfill_remediate 的 --threshold 被
argparse 声明却从未被消费 — 操作员传 ``--threshold 5`` 会被静默忽略 (接口
说谎), 实际阈值单一来源是哨兵模块常量。本守卫把 R233 的一次性 AST 排查固化
为家族回归网: 冻结清单内的夜链 CLI 脚本, 每个声明的 argparse 旗标必须有对应
消费点 (args.X 属性读或 getattr(args, "x") 字面量)。

守卫只认结构事实 (AST), 不做语义猜测; 家族清单是显式冻结列表 — 新增夜链
CLI 脚本必须显式入列 (漏列由 test_family_list_pins_real_scripts 的存在性
检查与 code review 把关, 不做目录级自动扫描以免误吞非 CLI 模块)。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 研究数据面夜链 (scripts/research_data_refresh.sh 五阶段) 及其直接协作脚本:
# flow 自愈编排 / 资金流哨兵 / bar 续传 / 龙虎榜续传 / court 重建 / 新鲜度门 /
# flow 回填执行体 (heal 阶段子进程)。零旗标模块 (哨兵) 也入列 — 家族成员
# 资格本身是冻结事实, 未来新增 CLI 即自动受守卫覆盖。
NIGHT_CHAIN_CLIS: tuple[str, ...] = (
    "scripts/flow_backfill_remediate.py",
    "scripts/fund_flow_freshness_sentinel.py",
    "scripts/btst_court_fetch.py",
    "scripts/fetch_lhb_daily.py",
    "scripts/btst_court_build.py",
    "scripts/research_freshness.py",
    "scripts/backfill_fund_flow_cache.py",
)


def _declared_flag_dests(source: str) -> dict[str, int]:
    """AST 解析 add_argument 声明 → {dest: line}。

    dest 解析: 显式 dest= 优先; 否则长旗标 ``--x-y`` → ``x_y`` (argparse 规则)。
    无可解析旗标名的 add_argument 调用按行号计入 "<positional>" 供
    test_flags_have_parseable_names 钉住 — 家族脚本当前不使用该形态。
    """
    dests: dict[str, int] = {}
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        dest = None
        for kw in node.keywords:
            if kw.arg == "dest" and isinstance(kw.value, ast.Constant) and isinstance(
                kw.value.value, str
            ):
                dest = kw.value.value
        if dest is None:
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                dest = first.value.lstrip("-").replace("-", "_")
        dests.setdefault(dest or "<positional>", node.lineno)
    return dests


def _consumed_arg_names(source: str) -> set[str]:
    """AST 收集 args 命名空间的全部读取形态。

    覆盖两种家族内实际使用的形态: ``args.x`` 属性读 (flow_backfill_remediate
    等) 与 ``getattr(args, "x", default)`` 字面量 (btst_court_build.py 的
    no_decomposition_refresh)。其他形态 (vars(args)/args[...]) 家族内不存在;
    出现时守卫会假阳性报死参数 — 那是扩展消费形态时的显式扩展点, 不是静默
    盲区 (fail visible)。
    """
    consumed: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "args"
        ):
            consumed.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "args"
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            consumed.add(node.args[1].value)
    return consumed


def test_family_list_pins_real_scripts():
    """冻结清单逐项存在 — 脚本改名/移除时显式失败, 不允许清单静默腐烂成
    空覆盖。CLI-ness 不在此断言: 零旗标成员 (哨兵) 是合法家族形态, 旗标面
    的守卫由主测试承担。"""
    for rel in NIGHT_CHAIN_CLIS:
        path = PROJECT_ROOT / rel
        assert path.is_file(), f"冻结清单成员缺失 (被改名/移除?): {rel}"


def test_flags_have_parseable_names():
    """add_argument 必须带可解析旗标名或显式 dest — 守卫解析不了就报出来,
    不静默跳过 (静默跳过 = 守卫盲区)。"""
    for rel in NIGHT_CHAIN_CLIS:
        source = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        dests = _declared_flag_dests(source)
        if "<positional>" in dests:
            pytest.fail(
                f"{rel} 存在守卫无法解析 dest 的 add_argument "
                f"(L{dests['<positional>']}) — 请扩展守卫或改用显式 dest"
            )


def test_night_chain_cli_flags_are_consumed():
    """主守卫: 家族内每个声明的旗标都有消费点 (args.X / getattr(args, "x"))。

    死参数 = 接口说谎: 调用方传参被静默忽略 (M14 --threshold 形态)。修复
    只有两种合法形态 — 接通消费或摘除声明; 不允许声明与消费脱钩。
    """
    for rel in NIGHT_CHAIN_CLIS:
        source = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        declared = _declared_flag_dests(source)
        consumed = _consumed_arg_names(source)
        dead = sorted(set(declared) - consumed)
        assert not dead, (
            f"{rel} 存在死参数 (声明未消费, 调用方传参被静默忽略): "
            + ", ".join(f"--{name} (L{declared[name]})" for name in dead)
        )


DEAD_FLAG_SOURCE = (
    "import argparse\n"
    "def main():\n"
    "    parser = argparse.ArgumentParser()\n"
    "    parser.add_argument('--ghost', type=int, default=1)\n"
    "    parser.parse_args()\n"
)

CONSUMED_FLAG_SOURCE = (
    "import argparse\n"
    "def main():\n"
    "    parser = argparse.ArgumentParser()\n"
    "    parser.add_argument('--ghost', type=int, default=1)\n"
    "    args = parser.parse_args()\n"
    "    print(args.ghost)\n"
)


def test_guard_detects_synthetic_dead_flag():
    """守卫自证 (guard-the-guard): 合成死参数必须被判死, 消费后必须放行 —
    防守卫未来退化为恒绿空转 (无 teeth 即无守卫)。"""
    dead = set(_declared_flag_dests(DEAD_FLAG_SOURCE)) - _consumed_arg_names(
        DEAD_FLAG_SOURCE
    )
    assert dead == {"ghost"}, f"合成死参数未被判定: {dead}"

    alive = set(_declared_flag_dests(CONSUMED_FLAG_SOURCE)) - _consumed_arg_names(
        CONSUMED_FLAG_SOURCE
    )
    assert not alive, "已消费旗标被误判死参数"

    dest_src = (
        "import argparse\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--legacy-name', dest='renamed', action='store_true')\n"
        "    args = parser.parse_args()\n"
        "    return args.renamed\n"
    )
    assert set(_declared_flag_dests(dest_src)) == {"renamed"}, "dest= 改名未按 dest 解析"
    assert not (
        set(_declared_flag_dests(dest_src)) - _consumed_arg_names(dest_src)
    ), "dest= 改名后被消费不得误报死参数"

    getattr_src = (
        "import argparse\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--opt-in', action='store_true')\n"
        "    args = parser.parse_args()\n"
        "    if getattr(args, 'opt_in', False):\n"
        "        pass\n"
    )
    assert not (
        set(_declared_flag_dests(getattr_src)) - _consumed_arg_names(getattr_src)
    ), "getattr(args, ...) 消费形态不得误报死参数"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
