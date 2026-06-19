from __future__ import annotations

import json

from src.execution.merge_approved_loader import load_merge_approved_tickers


def test_load_merge_approved_tickers_unions_explicit_and_ready_artifacts(tmp_path) -> None:
    merge_review_path = tmp_path / "btst_default_merge_review_latest.json"
    merge_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "merge_review_verdict": "ready_for_default_btst_merge_review",
            }
        ),
        encoding="utf-8",
    )
    merge_ranking_path = tmp_path / "btst_continuation_merge_candidate_ranking_latest.json"
    merge_ranking_path.write_text(
        json.dumps(
            {
                "top_candidate": {
                    "ticker": "300720",
                    "promotion_path_status": "merge_review_ready",
                }
            }
        ),
        encoding="utf-8",
    )

    tickers = load_merge_approved_tickers(
        explicit_tickers={"300505"},
        merge_review_path=merge_review_path,
        merge_ranking_path=merge_ranking_path,
    )

    assert tickers == {"300505", "300720"}


def test_load_merge_approved_tickers_does_not_fallback_to_ranking_when_review_holds(tmp_path) -> None:
    merge_review_path = tmp_path / "btst_default_merge_review_latest.json"
    merge_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "merge_review_verdict": "hold_continuation_lane",
            }
        ),
        encoding="utf-8",
    )
    merge_ranking_path = tmp_path / "btst_continuation_merge_candidate_ranking_latest.json"
    merge_ranking_path.write_text(
        json.dumps(
            {
                "top_candidate": {
                    "ticker": "300720",
                    "promotion_path_status": "merge_review_ready",
                }
            }
        ),
        encoding="utf-8",
    )

    tickers = load_merge_approved_tickers(
        explicit_tickers={"300505"},
        merge_review_path=merge_review_path,
        merge_ranking_path=merge_ranking_path,
    )

    assert tickers == {"300505"}


def test_load_merge_approved_tickers_corrupt_review_does_not_crash(tmp_path, caplog) -> None:
    """R106 同族 (R88/BH-017): merge_review sidecar JSON 损坏
    (运行中断 / 部分写入 / 磁盘错误留下的半截文件) 时, daily pipeline /
    BTST continuation 路径不再抛 raw JSONDecodeError 中断, 而是降级到
    只用 explicit_tickers + ranking fallback + warning 诊断。
    """
    merge_review_path = tmp_path / "btst_default_merge_review_latest.json"
    merge_review_path.write_text("{ truncated partial write  <-", encoding="utf-8")
    merge_ranking_path = tmp_path / "btst_continuation_merge_candidate_ranking_latest.json"
    merge_ranking_path.write_text(
        json.dumps(
            {
                "top_candidate": {
                    "ticker": "300720",
                    "promotion_path_status": "merge_review_ready",
                }
            }
        ),
        encoding="utf-8",
    )

    tickers = load_merge_approved_tickers(
        explicit_tickers={"300505"},
        merge_review_path=merge_review_path,
        merge_ranking_path=merge_ranking_path,
    )

    # corrupt review 不崩溃; review 损坏 → ranking_fallback_allowed 保持默认 True,
    # ranking 合法 → 300720 通过 ranking fallback 进入 (与 missing-review 语义一致)
    assert tickers == {"300505", "300720"}
    assert any("损坏" in rec.message or "corrupt" in rec.message.lower() for rec in caplog.records)


def test_load_merge_approved_tickers_corrupt_ranking_does_not_crash(tmp_path, caplog) -> None:
    """R106 同族 (R88/BH-017): merge_ranking sidecar JSON 损坏时,
    路径不再崩溃, 而是降级到只用 explicit + review + warning 诊断。"""
    merge_review_path = tmp_path / "btst_default_merge_review_latest.json"
    merge_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "merge_review_verdict": "ready_for_default_btst_merge_review",
            }
        ),
        encoding="utf-8",
    )
    merge_ranking_path = tmp_path / "btst_continuation_merge_candidate_ranking_latest.json"
    merge_ranking_path.write_text("{ truncated partial write  <-", encoding="utf-8")

    tickers = load_merge_approved_tickers(
        explicit_tickers={"300505"},
        merge_review_path=merge_review_path,
        merge_ranking_path=merge_ranking_path,
    )

    # corrupt ranking 不崩溃; review ready → 300720 通过 review 进入, ranking 损坏降级忽略
    assert tickers == {"300505", "300720"}
    assert any("损坏" in rec.message or "corrupt" in rec.message.lower() for rec in caplog.records)
