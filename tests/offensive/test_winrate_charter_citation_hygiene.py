"""宪章引用卫生守卫 (R211 Op1 建面, Op2 对抗收口) — 方向单一事实源的可机械约束面.

docs/winrate_payoff_optimization_charter.md 是 owner 指定的胜率/赔率工作线
长期方向单一事实源 (活文档, owner 2026-09-12 指令授权持续更新)。守卫只约束
可机械判定的引用卫生与注册锚不变量, 不约束内容与措辞 (活文档逐轮更新是
设计行为, 不是漂移):

- G1: 宪章引用的每个 R 轮号必须能在 AGENTS.md (轮次台账) 解析 — 防幻影
  轮号 (R170-R175 入册缺口先例: 交付在而台账无, 后续引用者无从核对)。
- G2: 宪章引用的每个 8 位哈希短引用必须出现在 AGENTS.md — 防幻影提交引用。
- G3: 杠杆台账标题字母唯一 — 防并行会话重复追加同一杠杆字母。
- G4 (Op2 钉): 杠杆 F 的注册锚数字 (R168 预注册决定性对比) 逐字钉死 —
  预注册一经注册不可回溯调整 (宪章 §4), 数字漂移即失真。
- G5 (Op2 钉): 杠杆 F 的 owner-gate 中立性 — 「缺什么」小节必须明示
  d1_run 转 gate 行为属 owner 决策; 披露不是授权。
- G6 (Op6 自证): 守卫本体在位自证 — 六个测试函数与两个解析正则必须在场
  (防守卫被静默删除; 函数体被掏空而签名在场的形态不可达, 如实成文)。

引用方向单向 (宪章 → AGENTS.md); 测试只读 tracked 文本文件, 零宿主数据
资产依赖 (R10 slot 自足纪律)。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHARTER_REL = "docs/winrate_payoff_optimization_charter.md"
AGENTS_REL = "AGENTS.md"

# G4: R168 注册锚的判定性数字 (预注册不可漂移; 字符串逐字取自宪章杠杆 F 小节)
REGISTERED_ANCHOR_PIN = (
    "n=460",
    "E=+1.77%",
    "n=341",
    "E=−5.74%",
    "[+2.49%, +11.94%]",
)

# G6: 守卫自证清单 (测试函数名 + 两个解析正则字面量)
SELF_PROOF_NAMES = (
    "test_charter_round_refs_resolve_in_agents_ledger",
    "test_charter_commit_shorthands_resolve_in_agents_ledger",
    "test_charter_lever_headings_letters_unique",
    "test_charter_lever_f_registered_anchor_numbers_pinned",
    "test_charter_lever_f_owner_gate_neutrality_pinned",
    "test_hygiene_guard_self_proof",
)
SELF_PROOF_PATTERNS = (r"\bR(\d{2,3})\b", r"`([0-9a-f]{8})`")


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _lever_f_section(text: str) -> str:
    match = re.search(r"^### 杠杆 F：.*?(?=^## )", text, flags=re.M | re.S)
    assert match, "杠杆 F 小节缺席"
    return match.group(0)


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


def test_charter_lever_f_registered_anchor_numbers_pinned():
    """G4: 杠杆 F 注册锚数字逐字在场 (预注册不可漂移)。"""
    section = _lever_f_section(_read(CHARTER_REL))
    missing = [s for s in REGISTERED_ANCHOR_PIN if s not in section]
    assert missing == [], "杠杆 F 注册锚数字漂移: " + ",".join(repr(s) for s in missing)


def test_charter_lever_f_owner_gate_neutrality_pinned():
    """G5: 杠杆 F 必须明示 owner gate 未决 (披露不是授权)。"""
    section = _lever_f_section(_read(CHARTER_REL))
    assert "owner 决策" in section, "杠杆 F 缺 owner 决策明示 (中立性失守)"
    assert "等 owner gate" in section, "杠杆 F 标题缺 owner gate 状态"


def test_hygiene_guard_self_proof():
    """G6: 守卫本体在位自证 (函数名 + 正则字面量; 掏空体而留签名的形态
    不可达属纵深边界, 如实成文不虚报)。"""
    source = Path(__file__).read_text(encoding="utf-8")
    missing_names = [n for n in SELF_PROOF_NAMES if n not in source]
    assert missing_names == [], "守卫测试函数缺席: " + ",".join(missing_names)
    missing_patterns = [p for p in SELF_PROOF_PATTERNS if p not in source]
    assert missing_patterns == [], "守卫解析正则缺席: " + ",".join(missing_patterns)
