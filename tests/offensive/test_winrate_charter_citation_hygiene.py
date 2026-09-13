"""宪章引用卫生守卫 (R211 Op1) — 方向单一事实源的引用可解析性机械约束.

docs/winrate_payoff_optimization_charter.md 是 owner 指定的胜率/赔率工作线
长期方向单一事实源 (活文档, owner 2026-09-12 指令授权持续更新)。本守卫只
约束引用卫生, 不约束内容与措辞 (活文档逐轮更新是设计行为, 不是漂移):

- G1: 宪章引用的每个 R 轮号必须能在 AGENTS.md (轮次台账) 解析 — 防幻影
  轮号 (R170-R175 入册缺口先例: 交付在而台账无, 后续引用者无从核对)。
- G2: 宪章引用的每个 8 位哈希短引用必须出现在 AGENTS.md — 防幻影提交引用。
- G3: 杠杆台账标题字母唯一 — 防并行会话重复追加同一杠杆字母。

引用方向单向 (宪章 → AGENTS.md): AGENTS.md 自身的引用密度与体积是入册
纪律的既有取舍, 不入约束面。测试只读两个 tracked 文本文件, 零宿主数据
资产依赖 (R10 slot 自足纪律)。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHARTER_REL = "docs/winrate_payoff_optimization_charter.md"
AGENTS_REL = "AGENTS.md"


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_charter_round_refs_resolve_in_agents_ledger():
    """G1: 宪章引用的 R 轮号必须在 AGENTS.md 有落点 (防幻影轮号)。"""
    agents = _read(AGENTS_REL)
    rounds = sorted(set(re.findall(r"\bR(\d{2,3})\b", _read(CHARTER_REL))))
    missing = [r for r in rounds if not re.search(r"\bR" + r + r"\b", agents)]
    assert missing == [], "宪章引用的轮号在 AGENTS.md 无解析: R" + ",".join(missing)


def test_charter_commit_shorthands_resolve_in_agents_ledger():
    """G2: 宪章引用的 8 位哈希短引用必须在 AGENTS.md 出现 (防幻影提交)。"""
    agents = _read(AGENTS_REL)
    shorthands = sorted(set(re.findall(r"`([0-9a-f]{8})`", _read(CHARTER_REL))))
    missing = [s for s in shorthands if s not in agents]
    assert missing == [], "宪章引用的哈希在 AGENTS.md 无解析: " + ",".join(missing)


def test_charter_lever_headings_letters_unique():
    """G3: 杠杆台账标题字母唯一 (防并行追加重复杠杆)。"""
    letters = re.findall(r"^### 杠杆 ([A-Z])", _read(CHARTER_REL), flags=re.M)
    assert len(letters) == len(set(letters)), "杠杆标题字母重复: " + ",".join(letters)
