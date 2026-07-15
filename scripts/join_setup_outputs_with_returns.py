"""Join logged live setup outputs with realized forward returns.

Reads ``data/reports/setup_output_log/*.jsonl`` (signal-time setup outputs from
the live logger) and, for each record whose forward bars now exist in
``price_cache``, computes T+1..T+10 returns (entry at T+1 open, exit at T+N
close). Writes a joined panel (``setup_output_panel.jsonl``) and prints coverage
plus a preliminary edge split by plan_eligible.

Forward returns fill in over time as ``price_cache`` accumulates: a T+10 signal
realizes ~10 sessions later. This is the out-of-sample panel that will
eventually answer cross-cycle robustness on genuine live data.

Run:
    uv run python scripts/join_setup_outputs_with_returns.py
"""

from __future__ import annotations

import glob
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from scripts.validate_auto300_gate_removal import (
    HORIZONS,
    _fmt,
    _forward_return,
    _summarize,
)

LOG_DIR = Path("data/reports/setup_output_log")
PANEL = Path("data/reports/setup_output_panel.jsonl")


def load_logged_records(log_dir: Path = LOG_DIR) -> list[dict]:
    records: list[dict] = []
    for path in sorted(glob.glob(str(log_dir / "*.jsonl"))):
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def compute_forward_returns(df: pd.DataFrame, signal_date_compact: str) -> dict[int, float | None]:
    """Entry at T+1 open, exit at T+horizon close; None if signal/forward absent."""
    df = df.reset_index(drop=True)
    matches = df.index[df["compact"].astype(str) == str(signal_date_compact)].tolist()
    if not matches:
        return {h: None for h in HORIZONS}
    idx = matches[0]
    return {h: _forward_return(df, idx, h) for h in HORIZONS}


def join_records(records: list[dict], series: dict[str, pd.DataFrame]) -> list[dict]:
    joined: list[dict] = []
    cache: dict[tuple[str, str], dict[int, float | None]] = {}
    for rec in records:
        ticker = str(rec.get("ticker", ""))
        signal_date = str(rec.get("signal_date", ""))
        key = (ticker, signal_date)
        if key not in cache:
            df = series.get(ticker)
            cache[key] = (
                compute_forward_returns(df, signal_date)
                if df is not None
                else {h: None for h in HORIZONS}
            )
        rets = cache[key]
        out = dict(rec)
        for h in HORIZONS:
            out[f"return_t{h}"] = rets[h]
        out["realized"] = rets[10] is not None
        joined.append(out)
    return joined


def _load_series_for_tickers(tickers: set[str], price_cache_dir: Path = Path("data/price_cache")) -> dict[str, pd.DataFrame]:
    """Load only the price series we need (the logged tickers) — cheap for --auto."""
    series: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        path = price_cache_dir / f"{ticker}.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if "date" not in df.columns:
            continue
        df["compact"] = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
        series[ticker] = df.sort_values("compact").reset_index(drop=True)
    return series


def backfill_panel(log_dir: Path = LOG_DIR, panel: Path = PANEL) -> tuple[list[dict], dict]:
    """Join logged outputs with any now-available forward returns; write the panel.

    Loads only the logged tickers' price series (not the whole universe), so it is
    cheap enough to run at the end of every ``--auto``. Returns ``(joined, stats)``.
    """
    records = load_logged_records(log_dir)
    if not records:
        return [], {"records": 0, "realized": 0}
    tickers = {str(r.get("ticker", "")) for r in records if r.get("ticker")}
    series = _load_series_for_tickers(tickers)
    joined = join_records(records, series)
    _write_panel(joined, panel)
    return joined, {
        "records": len(joined),
        "realized": sum(1 for j in joined if j["realized"]),
    }


def _write_panel(joined: list[dict], panel: Path = PANEL) -> None:
    panel.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(r, ensure_ascii=False, allow_nan=False, sort_keys=True) for r in joined)
    if payload:
        payload += "\n"
    fd, tmp = tempfile.mkstemp(dir=str(panel.parent), prefix=".panel_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, panel)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> None:
    joined, stats = backfill_panel()
    if not joined:
        print("no logged setup outputs yet (run --daily-action to accumulate)")
        return

    realized = [j for j in joined if j["realized"]]
    days = sorted({j["signal_date"] for j in joined})
    print(f"记录: {len(joined)}  信号日: {len(days)} ({days[0]}→{days[-1]})")
    print(f"已实现 T+10: {len(realized)}  待实现: {len(joined) - len(realized)}  → {PANEL}")
    if not realized:
        print("（前向收益尚未到期; 记录会随 price_cache 累积自动填充）")
        return
    print()
    for horizon in HORIZONS:
        print(f"--- T+{horizon} (已实现样本) ---")
        for elig in (True, False):
            vals = [j[f"return_t{horizon}"] for j in realized if j["plan_eligible"] is elig and j[f"return_t{horizon}"] is not None]
            label = "plan_eligible" if elig else "filtered   "
            print(f"  {label}: {_fmt(_summarize(vals))}")


if __name__ == "__main__":
    main()
