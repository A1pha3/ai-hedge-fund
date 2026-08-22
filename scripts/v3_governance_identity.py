#!/usr/bin/env python3
"""v3 治理身份目录工具 — Trial 启动准备的 owner 操作面 (2026-08-22).

子命令:
  generate --dir <dir>   一次性生成持久身份 (root + 每 namespace issuer 私钥
                         0600 + identity.json manifest); 已有 manifest 即拒绝
  check    --dir <dir>   加载 + 权限 + root 签名 + 私钥↔注册表配对全量重验

纪律: 身份目录绝不入 git; root.pem 是信任根 (泄露 = 整条链失守);
轮换 = 新 key_id 生成到新目录, 旧目录人工标记废弃。见
docs/runbooks/v3-governance-identity.md。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.screening.offensive.v3.evidence.governance_identity import (  # noqa: E402
    GovernanceIdentityError,
    generate_governance_identity,
    verify_identity_directory,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="一次性生成持久治理身份目录")
    gen.add_argument("--dir", required=True, type=Path)

    chk = sub.add_parser("check", help="全量重验既有身份目录")
    chk.add_argument("--dir", required=True, type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            manifest = generate_governance_identity(args.dir)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "directory": str(args.dir.resolve()),
                        "namespaces": manifest["namespaces"],
                        "valid_until": manifest["valid_until"],
                        "next": "妥善保管目录 (0600 私钥, 绝不入 git); "
                        "见 docs/runbooks/v3-governance-identity.md",
                    },
                    ensure_ascii=False,
                    indent=1,
                )
            )
            return 0
        summary = verify_identity_directory(args.dir)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0
    except GovernanceIdentityError as exc:
        print(
            json.dumps(
                {"ok": False, "code": exc.code, "details": exc.details},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
