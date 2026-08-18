"""court 证据资产哨点 — daemon 日链收尾的 advisory 检查 (2026-08-19, trap 22 运营覆盖层).

为什么存在: court 事件表的公式指纹漂移/表龄超限此前只在下次评估消费时被
45 天守卫 (review_btst_prior_court.table_freshness) 被动拦截 — "跨期评估前
先重建"全靠人想起。daemon 每天跑, 收尾多一次毫秒级检查即可让漂移当天可见
(trap 20 教训: 策略能力问题与运营覆盖问题是两层, 先有检测才有前者)。

advisory 语义: exit 恒 0, 输出一行诊断 — 告警进 pipeline 日志, 绝不阻塞
每日管道 (重建是人工决策, 按陷阱 22 两分支处置)。

口径与 review_btst_prior_court 对齐: 表龄按 manifest.built_at 日历天,
上限 45 天 (MAX_TABLE_AGE_DAYS 同值); 指纹 = btst_breakout.py 文件级
sha256 (与 build 护栏同口径, 注释变更也算漂移 — 处置分支见提示文本)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO / "data/research/btst_court/event_tables/manifest_v1.json"
DEFAULT_SETUP = REPO / "src/screening/offensive/setups/btst_breakout.py"
MAX_TABLE_AGE_DAYS = 45  # 与 review_btst_prior_court.MAX_TABLE_AGE_DAYS 同值 (口径锚)


def court_asset_problems(
    manifest: dict | None,
    current_setup_sha: str,
    today: date,
    max_age_days: int = MAX_TABLE_AGE_DAYS,
) -> list[str]:
    """纯函数: 返回 court 证据资产问题列表 (空 = 健康).

    判定顺序: manifest 缺失 → 公式指纹漂移 → 表龄超限; 每类至多一条,
    提示文本携带处置路径 (操作者不需要翻文档即可行动)。
    """
    if not isinstance(manifest, dict) or not manifest:
        return [
            "court manifest 缺失/不可读 — 证据资产不存在, 跨期评估不可用; "
            "重建: uv run python scripts/btst_court_fetch.py && uv run python scripts/btst_court_build.py"
        ]

    problems: list[str] = []
    fingerprint = str(manifest.get("formula_fingerprint", {}).get("btst_breakout_sha256", ""))
    if not fingerprint or fingerprint != current_setup_sha:
        problems.append(
            f"court 公式指纹漂移 (manifest {fingerprint[:8] or '∅'} != 当前 {current_setup_sha[:8]}) — "
            "按陷阱 22 处置: 先 git diff <manifest.git_sha>..HEAD -- btst_breakout.py 逐行确认变更性质, "
            "行为真实变化须开新版本文件, 同行为假阳性 (注释等) 用 build --rebuild-force"
        )

    built_at = manifest.get("built_at")
    try:
        age_days = (today - date.fromisoformat(str(built_at))).days if built_at else None
    except ValueError:
        age_days = None
    if age_days is None:
        problems.append("court manifest.built_at 缺失/非法 — 表龄不可证, 视同过期须重建")
    elif age_days > max_age_days:
        problems.append(
            f"court 表龄 {age_days} 天 > {max_age_days} (built_at {built_at}) — 跨期评估结论过期, "
            "重建: uv run python scripts/btst_court_fetch.py && uv run python scripts/btst_court_build.py"
        )
    return problems


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="court 证据资产哨点 (advisory, exit 恒 0)")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--setup-sha", default=None, help="显式指纹 (缺省现场计算 btst_breakout.py)")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    manifest: dict | None = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = None
    setup_sha = args.setup_sha or _file_sha256(DEFAULT_SETUP)

    problems = court_asset_problems(manifest, setup_sha, date.today())
    if not problems:
        window_end = (manifest or {}).get("window", {}).get("end", "?")
        print(f"court 资产哨点: 健康 (公式一致, window.end={window_end})")
    else:
        print("court 资产哨点: ⚠ " + "; ".join(problems))
    return 0  # advisory: 告警不改退出码, 绝不阻塞每日管道


if __name__ == "__main__":
    sys.exit(main())
