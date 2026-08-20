#!/usr/bin/env python3
"""前向配对 Trial Phase 4: 双臂 genesis 封存 driver (2026-08-20).

从生产 capital truth 为一个 trial 封存两臂等基因备份 — 既有
``TrialGenesisArchive.seal`` 机制 (等状态校验/守恒重验/内容寻址备份/幂等)
的命令行接线。本脚本只做三件事: 路径守卫 (canonical、无 symlink)、
dry-run 验证报告 (默认, 零写入)、显式 ``--seal`` 封存。

诚实边界: dry-run 不写任何文件; --seal 产物是离线 primitive — 不启动
Trial、不解除任何 fail-closed、不构成权限; exit-lane 基因未纳入
(capital-only genesis, lot 级继承留 Phase 5 lifecycle 修复)。

用法:
    uv run python scripts/v3_trial_genesis.py --capital PATH --root DIR --trial-id ID [--seal]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.orchestration.genesis import (
    TrialArmGenesisSource,
    TrialGenesisArchive,
)

_TRIAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


def _validate_root(root: Path) -> None:
    """Canonical 绝对路径, 逐组件 lstat 拒 symlink (镜像 v3_regime_trial 守卫)."""
    if not root.is_absolute():
        raise SystemExit(json.dumps({"error": "root_not_absolute", "root": str(root)}))
    probe = Path(root.anchor)
    for part in root.parts[1:]:
        probe = probe / part
        if probe.is_symlink():
            raise SystemExit(json.dumps({"error": "root_symlink_rejected", "component": str(probe)}))


def dry_run_report(capital_path: Path) -> dict:
    """等基因验证前缀 (零写入): 双臂规范化状态哈希 + 守恒重验。"""
    repo = CapitalRepository.open(capital_path)
    champion = TrialArmGenesisSource(repo)
    challenger = TrialArmGenesisSource(repo)
    c_state, ch_state = champion.normalized_state(), challenger.normalized_state()
    ok, details = repo.rebuild_projections()
    return {
        "capital_ledger": str(capital_path),
        "champion_normalized_hash": c_state.content_hash(),
        "challenger_normalized_hash": ch_state.content_hash(),
        "equal_state": c_state.content_hash() == ch_state.content_hash(),
        "conservation_rebuild": {"ok": ok, "details": list(details)},
        "sealable": bool(c_state.content_hash() == ch_state.content_hash() and ok),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paired-trial genesis sealing driver (dry-run by default)")
    ap.add_argument("--capital", required=True, type=Path, help="生产 capital ledger sqlite 路径")
    ap.add_argument("--root", required=True, type=Path, help="trial archive root (canonical, no symlinks)")
    ap.add_argument("--trial-id", required=True, help="trial id ([a-z0-9-]{3,64})")
    ap.add_argument("--seal", action="store_true", help="实际封存 (默认 dry-run 零写入)")
    args = ap.parse_args(argv)

    if not _TRIAL_ID_RE.fullmatch(args.trial_id):
        print(json.dumps({"error": "trial_id_rejected", "trial_id": args.trial_id}), file=sys.stderr)
        return 2
    if not args.capital.exists():
        print(json.dumps({"error": "capital_ledger_missing", "path": str(args.capital)}), file=sys.stderr)
        return 2
    _validate_root(args.root)

    if not args.seal:
        print(json.dumps(dry_run_report(args.capital), ensure_ascii=False, indent=1))
        return 0

    repo = CapitalRepository.open(args.capital)
    manifest = TrialGenesisArchive(args.root).seal(
        args.trial_id,
        TrialArmGenesisSource(repo),
        TrialArmGenesisSource(repo),
    )
    print(json.dumps({"sealed": True, "trial_id": manifest.trial_id,
                      "normalized_genesis_hash": manifest.normalized_genesis_hash}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
