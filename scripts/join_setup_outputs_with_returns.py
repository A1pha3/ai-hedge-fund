"""Join logged live setup outputs with realized forward returns.

Reads ``data/reports/setup_output_log/*.jsonl`` (signal-time setup outputs from
the live logger) and, for each record whose forward bars now exist in
``price_cache``, computes T+1..T+10 returns (entry at T+1 open, exit at T+N
close). Writes a joined panel (``setup_output_panel.jsonl``) and prints coverage
plus a preliminary edge split by plan_eligible.

R80 Op1: 每行额外标注计划层容量拦截 (``capacity_blocked``/``capacity_block_reason``,
来自当日 ``YYYYMMDD.capacity.jsonl`` 兄弟工件 — R79 Op3 持久化工件的消费端)。
被容量拦的票从未成交, 反事实对照若把它们算进「实际放行」会把从未下注的
结果混进通过组 (假象好 edge)。``*.capacity.jsonl`` 本体不进检测日志 join。

R81 Op1: 集合差重建 — R80 的 live 标注只覆盖工件存在之后; 0814 纪元以来
最大的容量自然实验 (0817/0821/0826/0827 共 25 只未获计划) 发生在工件存在
之前, 永久污染通过组。``reconstruct_capacity_index`` 用 eligible(检测日志
``plan_eligible=True``) − ledger 同信号日计划 (``trades`` 表) 的集合差对
「未获计划」做精确标注 (``capacity_block_source="reconstructed"``), 不依赖
估值重仿真; live 工件存在的日期 live 优先 (写器每次成功运行都落文件,
文件存在 = 当日正证据); 台账 ``daily_valuations.drawdown`` 机械排除回撤
熔断通道 (纪元内最深 -6.1%, 通道实证为空 — 守卫纯防御)。

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
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from scripts.validate_auto300_gate_removal import (
    HORIZONS,
    _fmt,
    _forward_return,
    _summarize,
)
from scripts.winrate_payoff_decomposition import ROUNDTRIP_COST, net_returns

LOG_DIR = Path("data/reports/setup_output_log")
PANEL = Path("data/reports/setup_output_panel.jsonl")
LEDGER_PATH = Path("data/paper_trading_v2/ledger.sqlite3")
# 每行披露的扣费基准 (R78 Op2: panel 在源头同排产出净口径列, 防未来消费者
# 重蹈 R77-Op2 同族 gross/净混算; gross 列保留 — 既有消费者兼容)。
NET_COST_BASIS = ROUNDTRIP_COST

# R81 Op1 集合差重建参数。纪元 = 台账 0814 新档; 前-纪元计划事实在归档台账
# (不同资本纪元), 跨纪元集合差会假阳性 — 永不重建。回撤守卫镜像
# daily_action_service 的回撤减半阈值语义 (≤ 该值 = 回撤窗口, 未获计划不可
# 归因容量, 不冒充容量拦); 阈值是 owner 冻结参数面, 漂移需新证据世代。
LEDGER_EPOCH_START = date(2026, 8, 14)
RECONSTRUCTION_DRAWDOWN_GUARD = -0.15
RECONSTRUCTED_REASON = "reconstructed_not_planned"


def _is_detection_log(path: str) -> bool:
    """只收检测日志; R79 的 ``YYYYMMDD.capacity.jsonl`` 兄弟工件是计划层拦截
    证据 (行 schema 完全不同), 混入 join 会以缺字段行污染 panel。"""
    return not Path(path).name.endswith(".capacity.jsonl")


def load_logged_records(log_dir: Path = LOG_DIR) -> list[dict]:
    records: list[dict] = []
    for path in sorted(p for p in glob.glob(str(log_dir / "*.jsonl")) if _is_detection_log(p)):
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _parse_signal_date(value: object) -> date | None:
    """compact ``YYYYMMDD`` → date; 畸形返回 None (advisory 语义, 不阻塞 join)。"""
    try:
        return datetime.strptime(str(value), "%Y%m%d").date()
    except ValueError:
        return None


def load_capacity_index(
    signal_dates: Iterable[object], log_dir: Path = LOG_DIR
) -> dict[str, dict[str, str]]:
    """signal_date(compact) → {ticker: reason} 只读索引 (R80 Op1)。

    复用 ``load_capacity_skips`` 单一实现 (文件缺失 → [] / 损坏行跳过, advisory
    语义); ticker 归一化 ``split(".")[0]`` 与检测日志纯码对齐。畸形 signal_date
    与读取异常都按无工件处理 — 容量标注是派生证据, 缺失降级为 False 不阻塞
    forward-return join (与写入侧 fail-open 语义同源)。
    """
    from src.screening.offensive.setup_output_log import load_capacity_skips

    index: dict[str, dict[str, str]] = {}
    for compact in sorted({str(d) for d in signal_dates}):
        signal_day = _parse_signal_date(compact)
        rows: list[dict] = []
        if signal_day is not None:
            try:
                rows = load_capacity_skips(signal_day, out_dir=log_dir)
            except Exception:
                rows = []
        index[compact] = {
            str(r.get("ticker", "")).split(".")[0]: str(r.get("reason", "") or "unknown")
            for r in rows
            if r.get("ticker")
        }
    return index


def reconstruct_capacity_index(
    records: list[dict],
    ledger_path: Path = LEDGER_PATH,
    *,
    log_dir: Path = LOG_DIR,
    epoch_start: date = LEDGER_EPOCH_START,
    drawdown_guard: float = RECONSTRUCTION_DRAWDOWN_GUARD,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], dict]:
    """eligible − ledger 计划 = 未获计划集合 (R81 Op1, 集合差精确重建)。

    集合差对「未获计划」是精确事实: eligible 来自检测日志 (``plan_eligible=True``,
    gate 已放行), 计划来自台账 ``trades`` 表 — 两者都是持久化事实, 不依赖估值
    重仿真。post-eligibility 未获计划的通道只有容量拦截 / 回撤减半·熔断 /
    幂等冲突; 回撤通道由当日 ``daily_valuations.drawdown`` 机械排除 (≤ guard
    = 回撤窗口 → 落 unclassified 不冒充容量拦), 幂等冲突需 --auto 同日重发
    变 provenance (纪元内未观测) — 如实登记为已知残余通道。

    live 工件存在的日期整日跳过 (写器每次成功运行都落文件, 文件存在 = 当日
    live 正证据, 集合差只填 live 静默日)。台账缺失/损坏 → advisory 降级
    (``ledger_available=False``, 零标注, 不崩 join)。

    Returns:
        (capacity_index, unclassified_index, meta)
        capacity_index:  date_compact → {ticker: RECONSTRUCTED_REASON}
        unclassified_index: date_compact → {ticker: "drawdown_window"|"valuation_missing"}
        meta: {"ledger_available": bool, "dates_considered": [compact...],
               "coverage_gaps": [(compact, ticker), ...]}  # 有计划无 eligible 行
    """
    eligible: dict[str, set[str]] = {}
    for rec in records:
        if rec.get("plan_eligible") is not True:
            continue
        ticker = str(rec.get("ticker", "")).split(".")[0]
        signal_day = _parse_signal_date(rec.get("signal_date"))
        if not ticker or signal_day is None or signal_day < epoch_start:
            continue
        eligible.setdefault(signal_day.strftime("%Y%m%d"), set()).add(ticker)

    capacity_index: dict[str, dict[str, str]] = {}
    unclassified_index: dict[str, dict[str, str]] = {}
    meta: dict = {"ledger_available": False, "dates_considered": [], "coverage_gaps": []}
    if not eligible:
        return capacity_index, unclassified_index, meta

    planned: dict[str, set[str]] = {}
    try:
        conn = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT ticker, signal_date FROM trades").fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return capacity_index, unclassified_index, meta
    meta["ledger_available"] = True
    for raw_ticker, raw_day in rows:
        ticker = str(raw_ticker or "").split(".")[0]
        day = str(raw_day or "").replace("-", "")
        if ticker and day:
            planned.setdefault(day, set()).add(ticker)

    def _drawdown(iso_day: str) -> float | None:
        try:
            conn = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT drawdown FROM daily_valuations WHERE trade_date = ?"
                    " ORDER BY rowid DESC LIMIT 1",
                    (iso_day,),
                ).fetchone()
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            return None
        if row is None or row[0] is None:
            return None
        return float(row[0])

    for compact in sorted(eligible):
        if (Path(log_dir) / f"{compact}.capacity.jsonl").exists():
            continue  # live 工件存在 = 当日正证据, 整日不重建
        iso_day = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
        drawdown = _drawdown(iso_day)
        planned_tickers = planned.get(compact, set())
        gap = planned_tickers - eligible[compact]
        if gap:
            meta["coverage_gaps"].extend((compact, t) for t in sorted(gap))
        not_planned = eligible[compact] - planned_tickers
        if not not_planned:
            continue
        meta["dates_considered"].append(compact)
        if drawdown is None:
            unclassified_index[compact] = {
                t: "reconstructed_unclassified_valuation_missing" for t in sorted(not_planned)
            }
        elif drawdown <= drawdown_guard:
            unclassified_index[compact] = {
                t: "reconstructed_unclassified_drawdown_window" for t in sorted(not_planned)
            }
        else:
            capacity_index[compact] = {t: RECONSTRUCTED_REASON for t in sorted(not_planned)}
    return capacity_index, unclassified_index, meta


def compute_forward_returns(df: pd.DataFrame, signal_date_compact: str) -> dict[int, float | None]:
    """Entry at T+1 open, exit at T+horizon close; None if signal/forward absent."""
    df = df.reset_index(drop=True)
    matches = df.index[df["compact"].astype(str) == str(signal_date_compact)].tolist()
    if not matches:
        return {h: None for h in HORIZONS}
    idx = matches[0]
    return {h: _forward_return(df, idx, h) for h in HORIZONS}


def join_records(
    records: list[dict],
    series: dict[str, pd.DataFrame],
    capacity_index: dict[str, dict[str, str]] | None = None,
    *,
    reconstructed_index: dict[str, dict[str, str]] | None = None,
    unclassified_index: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Join 检测日志与已实现前向收益, 并标注计划层容量拦截 (R80 Op1)。

    ``capacity_index`` 缺省/无该日/无该票 → ``capacity_blocked=False`` 且
    ``capacity_block_reason=""`` — 旧行为逐位兼容 (R79 Op3 工件出现前的
    历史行即此形态)。R81 Op1 增加三列: ``capacity_block_source``
    ("live"|"reconstructed"|"", live 优先) 与 ``not_planned_unclassified``
    (回撤窗口/估值缺失的未获计划 — 不冒充容量拦, 也不混入通过组, review
    单独披露)。
    """
    joined: list[dict] = []
    cache: dict[tuple[str, str], dict[int, float | None]] = {}
    capacity_index = capacity_index or {}
    reconstructed_index = reconstructed_index or {}
    unclassified_index = unclassified_index or {}
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
        gross = []
        for h in HORIZONS:
            out[f"return_t{h}"] = rets[h]
            gross.append(rets[h])
        # panel 列单位是百分数 (与 _forward_return 一致); net_returns 吃小数 —
        # /100 进、×100 出, 净列保持百分数同单位。
        nets = net_returns([None if g is None else g / 100.0 for g in gross])
        for h, net in zip(HORIZONS, nets):
            out[f"return_t{h}_net"] = None if net is None else net * 100.0
        out["net_cost_basis"] = NET_COST_BASIS
        out["realized"] = rets[10] is not None
        capacity = capacity_index.get(signal_date, {})
        reconstructed = reconstructed_index.get(signal_date, {})
        unclassified = unclassified_index.get(signal_date, {})
        out["capacity_blocked"] = ticker in capacity or ticker in reconstructed
        out["capacity_block_reason"] = capacity.get(ticker, "") or reconstructed.get(ticker, "")
        out["capacity_block_source"] = (
            "live" if ticker in capacity else ("reconstructed" if ticker in reconstructed else "")
        )
        out["not_planned_unclassified"] = ticker in unclassified
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


def backfill_panel(
    log_dir: Path = LOG_DIR,
    panel: Path = PANEL,
    price_cache_dir: Path = Path("data/price_cache"),
    ledger_path: Path = LEDGER_PATH,
) -> tuple[list[dict], dict]:
    """Join logged outputs with any now-available forward returns; write the panel.

    Loads only the logged tickers' price series (not the whole universe), so it is
    cheap enough to run at the end of every ``--auto``. Returns ``(joined, stats)``.
    """
    records = load_logged_records(log_dir)
    if not records:
        return [], {"records": 0, "realized": 0}
    tickers = {str(r.get("ticker", "")) for r in records if r.get("ticker")}
    series = _load_series_for_tickers(tickers, price_cache_dir=price_cache_dir)
    capacity_index = load_capacity_index(
        {str(r.get("signal_date", "")) for r in records}, log_dir=log_dir
    )
    reconstructed_index, unclassified_index, recon_meta = reconstruct_capacity_index(
        records, ledger_path=ledger_path, log_dir=log_dir
    )
    joined = join_records(
        records,
        series,
        capacity_index,
        reconstructed_index=reconstructed_index,
        unclassified_index=unclassified_index,
    )
    _write_panel(joined, panel)
    return joined, {
        "records": len(joined),
        "realized": sum(1 for j in joined if j["realized"]),
        "capacity_live": sum(1 for j in joined if j["capacity_block_source"] == "live"),
        "capacity_reconstructed": sum(
            1 for j in joined if j["capacity_block_source"] == "reconstructed"
        ),
        "recon_ledger_available": recon_meta["ledger_available"],
        "recon_coverage_gaps": len(recon_meta["coverage_gaps"]),
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
    capacity_live = stats.get("capacity_live", 0)
    capacity_recon = stats.get("capacity_reconstructed", 0)
    if capacity_live or capacity_recon:
        print(
            f"容量拦标注: live {capacity_live} · 集合差重建 {capacity_recon}"
            f" (台账可用={stats.get('recon_ledger_available')}"
            f", 计划无日志行 {stats.get('recon_coverage_gaps')})"
        )
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
