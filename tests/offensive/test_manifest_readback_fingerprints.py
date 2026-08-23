"""manifest 授权指纹回读 (2026-08-23 对抗审查 Item 4) — 授权≡验证由构造成立.

事件类 (2026-08-20): 授权侧 (refresh 内存帧) 与验证侧 (loader 读盘) 是两条
独立计算路径, 写入窗口内的任何分歧 → 授权指纹描述的不是落盘事实 → 数小时后
loader 复算 mismatch → 票在扫描里无痕消失. 修复后授权指纹从落盘文件经与
loader 相同的 secure reader 回读 — 本文件钉死: 即使写入路径产生分歧 (写出的
字节 ≠ 内存帧), 授权仍然绑定**文件真相**, 与 loader 复算逐字节一致.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from src.screening.offensive.cache_readiness import SuspensionEvidence
from src.screening.offensive.pit_evidence import canonical_price_fingerprint
from src.utils.secure_files import read_secure_csv_frame

TRADE_DATE = "20260820"
TICKER = "000001"


def _daily_batch(pct: float = 9.9) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": f"{TICKER}.SZ",
                "trade_date": TRADE_DATE,
                "open": 10.0,
                "high": 11.0,
                "low": 9.9,
                "close": 11.0,
                "pct_chg": pct,
                "vol": 12345.0,
            }
        ]
    )


def _seed_price_cache(price_dir, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    frame.to_csv(price_dir / f"{TICKER}.csv", index=False)


def _seed_flow_cache(flow_dir) -> None:
    rows = [
        {
            "date": d,
            "close": "10.0",
            "pct_change": "1.0",
            "main_net_inflow": "1000.0",
            "main_net_pct": "0.1",
            "big_net_inflow": "500.0",
            "super_big_net_inflow": "500.0",
            "medium_net_inflow": "0.0",
            "small_net_inflow": "0.0",
            "ticker": TICKER,
        }
        for d in ("20260801", "20260802", "20260803", "20260804", "20260805")
    ]
    pd.DataFrame(rows).to_csv(flow_dir / f"{TICKER}.csv", index=False)


def _run_refresh(tmp_path, *, price_rows=None):
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_dir = tmp_path / "price"
    flow_dir = tmp_path / "flow"
    price_dir.mkdir(parents=True)
    flow_dir.mkdir(parents=True)
    if price_rows:
        _seed_price_cache(price_dir, price_rows)
    _seed_flow_cache(flow_dir)
    result = refresh_daily_action_caches(
        TRADE_DATE,
        price_cache_dir=price_dir,
        fund_flow_cache_dir=flow_dir,
        snapshot_dir=tmp_path / "snapshots",
        daily_prices_df=_daily_batch(),
        target_tickers=[TICKER],
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 8, 20), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )
    return result, price_dir, flow_dir


def test_authorized_fingerprint_equals_loader_recompute_from_written_file(tmp_path):
    """授权指纹必须等于 loader 对同一落盘文件的复算 (read-after-write 不变量)."""
    prior = [
        {"date": d, "close": "10.0", "open": "10.0", "high": "10.2", "low": "9.8",
         "pct_change": "1.0", "volume": "1000"}
        for d in ("20260813", "20260814", "20260817", "20260818", "20260819")
    ]
    result, price_dir, _ = _run_refresh(tmp_path, price_rows=prior)

    outcome = result.outcomes[TICKER]
    assert outcome.evidence_fingerprints.get("price"), "授权指纹应存在"

    frame = read_secure_csv_frame(price_dir / f"{TICKER}.csv", max_bytes=10 * 1024 * 1024)
    expected = canonical_price_fingerprint(frame, TICKER, date(2026, 8, 20))
    assert outcome.evidence_fingerprints["price"] == expected


def test_authorized_fingerprint_binds_file_truth_when_write_diverges(tmp_path):
    """写入分歧场景 (8-20 事件类): 写出的字节 ≠ 内存帧 → 授权必须跟文件走.

    构造: 包装 atomic_write_csv, 在正常写盘后向文件追加一行合法历史行 —
    模拟写入路径与内存帧的分歧. 旧实现 (内存帧授权) 会给出 ≠ 文件的指纹,
    loader 数小时后 mismatch → 票无痕消失; 新实现 (回读授权) 指纹绑定文件
    真相, 与 loader 复算恒等.
    """
    import src.screening.offensive.cache_refresh as cr
    from src.utils.atomic_files import atomic_write_csv as _real_write

    def _tampering_write(path, frame):
        _real_write(path, frame)
        # 正常写完后追加一行 ≤ trade_date 的历史行 (写入路径分歧)
        tampered = pd.read_csv(path, dtype=str)
        tampered.loc[len(tampered)] = {
            "date": "20260812",
            "close": "9.0",
            "open": "9.0",
            "high": "9.1",
            "low": "8.9",
            "pct_change": "-0.5",
            "volume": "700",
        }
        tampered.to_csv(path, index=False)

    original = cr.atomic_write_csv
    cr.atomic_write_csv = _tampering_write
    try:
        result, price_dir, _ = _run_refresh(tmp_path)
    finally:
        cr.atomic_write_csv = original

    outcome = result.outcomes[TICKER]
    frame = read_secure_csv_frame(price_dir / f"{TICKER}.csv", max_bytes=10 * 1024 * 1024)
    expected = canonical_price_fingerprint(frame, TICKER, date(2026, 8, 20))
    # 授权绑定被篡改后的文件真相 (而非内存帧) — loader 复算必然一致
    assert outcome.evidence_fingerprints["price"] == expected


def test_readback_failure_yields_no_fingerprint(tmp_path, monkeypatch):
    """回读失败 (如目录被替换为 symlink) → 无指纹 → capability 阻断 (fail-closed)."""
    from src.screening.offensive import cache_refresh as cr

    def _boom(*_args, **_kwargs):
        from src.utils.secure_files import SecureReadError

        raise SecureReadError("simulated read-back failure")

    monkeypatch.setattr(cr, "read_secure_csv_frame", _boom)

    result, _price_dir, _flow_dir = _run_refresh(tmp_path)
    assert result.outcomes[TICKER].evidence_fingerprints.get("price") is None


def test_shared_reader_rejects_symlinked_cache_file(tmp_path):
    """共享 secure reader 本体: symlink 缓存文件拒绝 (单一实现的承重面)."""
    import os

    from src.utils.secure_files import SecureReadError, read_secure_csv_frame

    real = tmp_path / "real.csv"
    real.write_text("date,close\n20260820,10.0\n", encoding="utf-8")
    link = tmp_path / "link.csv"
    os.symlink(real, link)

    try:
        read_secure_csv_frame(link, max_bytes=1024)
    except SecureReadError:
        return
    raise AssertionError("symlinked cache file must be rejected")
