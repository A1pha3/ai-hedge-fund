"""scripts/backfill_fund_flow.py — load_journal_tickers 契约测试.

C-TRIGGER-STRENGTH unblock (20260710): 默认 load_candidate_tickers 只取最新报告的
~30 只 ticker, 不覆盖历史 BUY 的 ticker → 历史 fund_flow 缺失, trigger_strength
验证被 data-block. load_journal_tickers 从 paper_trading journal 取全量历史 BUY
ticker, 配合 --fresh-days 0 恢复 BUY 日资金流.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.backfill_fund_flow import load_journal_tickers


def _write_journal(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def test_load_journal_tickers_extracts_unique_buy_tickers(tmp_path):
    """从 journal 提取所有 BUY ticker, 去重保序, 忽略 EXIT/SKIP."""
    journal = tmp_path / "journal.jsonl"
    records = [
        {"action": "BUY", "ticker": "688037", "date": "20260115", "setup": "btst_breakout"},
        {"action": "BUY", "ticker": "300903", "date": "20260116", "setup": "btst_breakout"},
        {"action": "EXIT", "ticker": "688037", "date": "20260115", "reasoning": "realized=+5%"},
        # 重复 ticker, 去重
        {"action": "BUY", "ticker": "688037", "date": "20260201", "setup": "btst_breakout"},
        # 非 BUY, 忽略
        {"action": "SKIP", "ticker": "000001", "date": "20260117", "reasoning": "未触发"},
        {"action": "BUY", "ticker": "600703", "date": "20260120", "setup": "oversold_bounce"},
    ]
    _write_journal(journal, records)
    tickers = load_journal_tickers(journal)
    # 去重保序: 688037 只出现一次 (首次位置), 300903, 600703; 无 000001 (SKIP)
    assert tickers == ["688037", "300903", "600703"], f"got {tickers}"


def test_load_journal_tickers_missing_file_returns_empty(tmp_path):
    """journal 不存在 → 空列表 (不抛异常)."""
    assert load_journal_tickers(tmp_path / "nonexistent.jsonl") == []


def test_load_journal_tickers_skips_corrupt_lines(tmp_path):
    """损坏的 JSON 行跳过, 不中断解析 (与 PaperTracker._load_journal 同口径)."""
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        '{"action": "BUY", "ticker": "688037", "date": "20260115"}\n' "this is not json\n" '{"action": "BUY", "ticker": "300903", "date": "20260116"}\n',
        encoding="utf-8",
    )
    tickers = load_journal_tickers(journal)
    assert tickers == ["688037", "300903"], f"损坏行应跳过, got {tickers}"
