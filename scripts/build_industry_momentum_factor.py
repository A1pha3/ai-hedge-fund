#!/usr/bin/env python3
"""行业动量横截面因子 (R62, owner 数据效率工作线④; 对抗审查 A/B/C 落 C).

主规格 (**预注册单一规格, 不做回看期扫描** — 规格扫描=多重比较陷阱):
    factor(D, 票) = 该票 PIT 行业的指数 20 会话收盘动量
                  = close(t_last) / close(t_last-20) − 1
其中 t_last = 严格早于 D 的最近会话收盘 (T0 收盘决策时, T-1 晚间已发布的
指数收盘可用 — PIT 安全), 行业取 court 表 `industry_name` (PIT 派生列) 经
`_industry_codes.json` 映射到 801xxx.SI 指数序列。

行业缺失/映射缺失 → 该行 NaN 并如实计数 (不冒充中性值)。全宇宙覆盖 —
与 LHB 席位因子 (5.67%, 工厂拒评) 形成对照。

输出: factor csv (signal_date,ts_code,factor) → 喂
scripts/factor_factory_eval.py --factor-csv。

用法 (uv run, 仓库根):
  uv run python scripts/build_industry_momentum_factor.py \
      --out data/research/btst_court/factors/industry_momentum_v0.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from fetch_lhb_daily import (  # noqa: E402
    LhbFetchError,
    load_calendar_sessions,
)

REPO_ROOT = _SCRIPTS.parent
DEFAULT_COURT = REPO_ROOT / "data/research/btst_court/event_tables/event_table_v1.csv.gz"
DEFAULT_IND_DIR = REPO_ROOT / "data/industry_index_cache"
DEFAULT_CALENDAR = REPO_ROOT / "data/reports/trade_calendar.json"
LOOKBACK = 20


class IndustryFactorError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise IndustryFactorError(code, details)


def _load_code_map(ind_dir: Path) -> dict[str, str]:
    """行业名 → 801xxx.SI。"""
    path = ind_dir / "_industry_codes.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IndustryFactorError(
            "industry_code_map_not_found", {"path": str(path)}) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IndustryFactorError(
            "industry_code_map_unreadable", {"path": str(path)}) from exc
    if not isinstance(raw, dict) or not raw:
        _typed("industry_code_map_malformed", {"path": str(path)})
    return {str(v): str(k) for k, v in raw.items()}  # name → code


def _index_momentum(ind_dir: Path, code: str, sessions: list[str],
                    day: str, lookback: int) -> float | None:
    """止于 D 之前最近会话的 lookback 会话收盘动量; 序列缺段返回 None。"""
    path = ind_dir / f"{code}.csv"
    if not path.is_file():
        return None
    frame = pd.read_csv(path, dtype={"trade_date": str})
    closes = dict(zip(frame["trade_date"], frame["close"].astype(float)))
    prior = [s for s in sessions if s < day]
    if len(prior) < lookback + 1:
        return None
    t_last, t_start = prior[-1], prior[-1 - lookback]
    c_last, c_start = closes.get(t_last), closes.get(t_start)
    if not c_last or not c_start or c_start == 0:
        return None
    return c_last / c_start - 1.0


def build_factor(
    *,
    court_path: Path,
    ind_dir: Path,
    calendar_path: Path,
    lookback: int = LOOKBACK,
) -> tuple[pd.DataFrame, dict]:
    if not court_path.is_file():
        _typed("court_table_not_found", {"path": str(court_path)})
    ev = pd.read_csv(court_path, dtype={"signal_date": str})
    for col in ("signal_date", "ts_code", "industry_name"):
        if col not in ev.columns:
            _typed("court_missing_column", {"column": col})
    sessions = load_calendar_sessions(calendar_path)
    if sessions[-1] < ev["signal_date"].max():
        _typed("calendar_stale",
               {"calendar_max": sessions[-1],
                "court_max": str(ev["signal_date"].max())})
    name_to_code = _load_code_map(ind_dir)

    # 每行业每信号日只算一次动量 (去重: 行业×日)
    pairs = ev[["signal_date", "industry_name"]].drop_duplicates()
    momentum_cache: dict[tuple[str, str], float | None] = {}
    for _, row in pairs.iterrows():
        key = (str(row["industry_name"]), str(row["signal_date"]))
        if key in momentum_cache:
            continue
        code = name_to_code.get(key[0])
        momentum_cache[key] = (
            _index_momentum(ind_dir, code, sessions, key[1], lookback)
            if code else None
        )

    rows, missing_industry, missing_momentum = [], 0, 0
    for _, row in ev.iterrows():
        name = row["industry_name"]
        if pd.isna(name) or not str(name).strip():
            missing_industry += 1
            continue
        code = name_to_code.get(str(name))
        value = momentum_cache.get((str(name), str(row["signal_date"])))
        if value is None:
            missing_momentum += 1
            continue
        rows.append({
            "signal_date": str(row["signal_date"]),
            "ts_code": str(row["ts_code"]),
            "factor": value,
        })
    factor = pd.DataFrame(rows, columns=["signal_date", "ts_code", "factor"])
    summary = {
        "court_rows": int(len(ev)),
        "factor_rows": int(len(factor)),
        "missing_industry_rows": missing_industry,
        "missing_momentum_rows": missing_momentum,
        "lookback": lookback,
    }
    return factor, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court", default=str(DEFAULT_COURT))
    parser.add_argument("--ind-dir", default=str(DEFAULT_IND_DIR))
    parser.add_argument("--calendar", default=str(DEFAULT_CALENDAR))
    parser.add_argument("--lookback", type=int, default=LOOKBACK)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        factor, summary = build_factor(
            court_path=Path(args.court), ind_dir=Path(args.ind_dir),
            calendar_path=Path(args.calendar), lookback=args.lookback)
    except (LhbFetchError, IndustryFactorError) as exc:
        code = getattr(exc, "code", "industry_factor_failed")
        details = getattr(exc, "details", {})
        print(json.dumps({"ok": False, "code": code, "details": details},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    factor.to_csv(out, index=False)
    print(json.dumps({"ok": True, **summary, "out": str(out)},
                     ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
