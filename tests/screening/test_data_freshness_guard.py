"""Tests for data_freshness_guard.py — P6-1 数据新鲜度守门员."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.screening.data_freshness_guard import (
    _days_between,
    _normalize_date,
    _render_freshness_summary,
    apply_freshness_confidence_penalty,
    check_data_freshness,
)


class TestNormalizeDate:
    def test_compact_to_hyphenated(self) -> None:
        assert _normalize_date("20260611") == "2026-06-11"

    def test_already_hyphenated(self) -> None:
        assert _normalize_date("2026-06-11") == "2026-06-11"

    def test_empty(self) -> None:
        assert _normalize_date("") == ""

    def test_none_like(self) -> None:
        assert _normalize_date("None") == "None"


class TestDaysBetween:
    def test_same_day(self) -> None:
        assert _days_between("2026-06-11", "2026-06-11") == 0

    def test_one_day(self) -> None:
        assert _days_between("2026-06-10", "2026-06-11") == 1

    def test_week(self) -> None:
        assert _days_between("2026-06-04", "2026-06-11") == 7

    def test_reversed(self) -> None:
        assert _days_between("2026-06-12", "2026-06-11") == 0

    def test_invalid(self) -> None:
        assert _days_between("invalid", "2026-06-11") == 0


class TestCheckDataFreshness:
    def test_fresh_when_no_cache_and_no_reports(self) -> None:
        """No cache and no reports → still returns fresh=True (graceful)."""
        result = check_data_freshness(trade_date="20260611", cache_path=Path("/nonexistent/cache.sqlite"))
        assert result["fresh"] is True
        assert result["warning_count"] == 0

    def test_stale_report_detected(self, tmp_path: Path) -> None:
        """When reports_dir has only old reports, freshness check should flag it."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        # Create an old report
        old_report = reports_dir / "auto_screening_20260601.json"
        old_report.write_text(json.dumps({"recommendations": []}), encoding="utf-8")

        result = check_data_freshness(trade_date="20260611", reports_dir=reports_dir)
        assert result["fresh"] is False
        assert result["warning_count"] >= 1
        # Should have a HIGH severity warning about the report
        warning_sources = [w["source"] for w in result["warnings"]]
        assert "report_file" in warning_sources

    def test_today_report_is_fresh(self, tmp_path: Path) -> None:
        """When today's report exists, freshness check passes."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        today_report = reports_dir / "auto_screening_20260611.json"
        today_report.write_text(json.dumps({"recommendations": []}), encoding="utf-8")

        # R118: 显式 cache_path (不存在的路径) 避免依赖机器默认缓存状态 ——
        # 否则本机若有 schema 不匹配的真实缓存会让测试结果非确定性。
        result = check_data_freshness(
            trade_date="20260611",
            reports_dir=reports_dir,
            cache_path=tmp_path / "nonexistent.sqlite",
        )
        assert result["fresh"] is True

    def test_trade_date_normalized(self) -> None:
        """trade_date is normalized to YYYY-MM-DD in output."""
        result = check_data_freshness(trade_date="20260611")
        assert result["trade_date"] == "2026-06-11"

    def test_cache_audit_failure_logs_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """BH-017 drain: when the cache DB connection fails, the freshness
        audit must (a) still return gracefully AND (b) emit a warning so the
        silent false-"all fresh" risk is diagnosable."""
        import logging
        import sqlite3

        from src.screening.data_freshness_guard import _check_cache_freshness

        bad_cache = tmp_path / "cache.sqlite"
        bad_cache.touch()

        # Force sqlite3.connect to raise so the OUTER except (which warns)
        # fires rather than the inner per-source handlers.
        def boom(*_args, **_kwargs):
            raise sqlite3.OperationalError("simulated locked DB")

        monkeypatch.setattr(sqlite3, "connect", boom)

        with caplog.at_level(logging.WARNING, logger="src.screening.data_freshness_guard"):
            result = _check_cache_freshness("2026-06-11", bad_cache)

        # Graceful: returns empty dict (no crash).
        assert result == {}
        # Observability: warns that the audit was unavailable.
        assert any("cache freshness audit unavailable" in rec.message.lower() for rec in caplog.records), f"Expected cache-audit warning, got: {[rec.message for rec in caplog.records]}"

    def test_per_source_query_failure_marks_freshness_unknown_not_fresh(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """R118 / 新鲜度门正确性: 单源新鲜度查询失败时, 该源应标记为"未知"
        (不确定), 让 ``check_data_freshness`` 保守判 ``fresh=False``,
        不能让查询失败被静默吞掉后误判 "all fresh"。

        autodev-7 / disease G update: the old ``SELECT MAX(date)`` query was
        replaced by a key-scan (``SELECT key FROM cache WHERE key LIKE ?``).
        R118's conservative safety is preserved: when the key-scan itself
        raises (locked DB / schema drift on the key column), the source is
        marked ``unknown`` → ``check_data_freshness`` treats it as not-fresh.
        This is distinct from ``unavailable`` (key-scan OK, no parseable key —
        a schema limit, not a failure).
        """
        import sqlite3

        from src.screening import data_freshness_guard as dfg

        cache = tmp_path / "cache.sqlite"
        # Real openable DB with the production schema.
        conn = sqlite3.connect(cache)
        conn.execute("CREATE TABLE cache (key TEXT, value BLOB, expires_at INTEGER)")
        conn.commit()
        conn.close()

        # Simulate a key-scan query failure (locked DB / schema drift).
        orig_connect = sqlite3.connect

        class _WrappedConn:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *a, **kw):
                # The daily_prices key-scan: SELECT key FROM cache WHERE key LIKE ?
                if "SELECT key FROM cache" in sql and a and "%akshare::%daily" in str(a[0]):
                    raise sqlite3.OperationalError("simulated locked DB")
                return self._real.execute(sql, *a, **kw)

            def close(self):
                self._real.close()

        def patched_connect(*args, **kwargs):
            return _WrappedConn(orig_connect(*args, **kwargs))

        monkeypatch.setattr(sqlite3, "connect", patched_connect)

        result = dfg.check_data_freshness(trade_date="20260611", cache_path=cache)

        # 保守安全默认: 查询异常 → unknown → fresh=False (不能误判 all fresh)
        assert result["fresh"] is False, "新鲜度门正确性: daily_prices key-scan 失败时该源应标记未知, " "check_data_freshness 应保守判 fresh=False, 不能误报 all-fresh 绕过数据安全门"

    def test_daily_prices_freshness_uses_akshare_key_end_date(self, tmp_path: Path) -> None:
        """autodev-7 / disease G: the cache schema is (key, value, expires_at) —
        there is NO ``date`` column. The old query ``SELECT MAX(date) FROM cache
        WHERE key LIKE '%daily_prices%'`` always raises 'no such column: date',
        so every source was permanently marked UNKNOWN (false stale-positive).
        R118 caught the missing column but only fixed the fallback, not the
        query. The fix parses the end_date embedded in akshare price keys
        (format ``prices:akshare::ashare_{ticker}_{start}_{end}_daily``) to
        determine the real latest data date.

        This test seeds a cache with the real schema and akshare key format,
        then asserts the freshness check reads the embedded date instead of
        failing on a non-existent ``date`` column.
        """
        import sqlite3

        from src.screening import data_freshness_guard as dfg

        cache = tmp_path / "cache.sqlite"
        conn = sqlite3.connect(cache)
        # REAL schema (no date column) — this is what the production cache uses.
        conn.execute("CREATE TABLE cache (key TEXT, value BLOB, expires_at INTEGER)")
        # Seed an akshare price key with end_date 20260610 (1 day before trade_date).
        conn.execute(
            "INSERT INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            ("prices:akshare::ashare_000001_20260601_20260610_daily", b"", 0),
        )
        conn.commit()
        conn.close()

        result = dfg.check_data_freshness(trade_date="20260611", cache_path=cache)

        # The daily_prices source must report the real date parsed from the key,
        # not 'unknown'. trade_date=20260611, latest=20260610 → 1 day stale,
        # within max_stale_days=1 → fresh for this source.
        daily_warning = next(
            (w for w in result["warnings"] if w.get("source") == "daily_prices"),
            None,
        )
        # Either fresh (no warning) or a warning with a real date (not 'unknown').
        if daily_warning is not None:
            assert daily_warning["latest_date"] != "unknown", (
                "daily_prices must use the date parsed from the akshare key, "
                "not 'unknown' (disease G: the date column never existed)"
            )

    def test_cache_schema_without_date_column_does_not_permanently_mark_unknown(
        self, tmp_path: Path
    ) -> None:
        """autodev-7 / disease G regression: a cache with the REAL production
        schema (key, value, expires_at — NO date column) must not cause every
        source to be permanently marked UNKNOWN. Before the fix, the date-column
        query failed for all 3 sources on every run, producing a permanent
        false stale-positive. After the fix, sources whose dates can be parsed
        from keys report real dates; sources that genuinely cannot be checked
        are labeled honestly (not silently false-positive)."""
        import sqlite3

        from src.screening import data_freshness_guard as dfg

        cache = tmp_path / "cache.sqlite"
        conn = sqlite3.connect(cache)
        conn.execute("CREATE TABLE cache (key TEXT, value BLOB, expires_at INTEGER)")
        # No akshare keys seeded → daily_prices has no parseable keys.
        conn.commit()
        conn.close()

        result = dfg.check_data_freshness(trade_date="20260611", cache_path=cache)

        # With no parseable keys, the source should NOT be a false stale-positive
        # 'unknown'. It should be either absent (no warning) or honestly marked
        # as 'unavailable' (schema limit), distinct from 'unknown' (conservative
        # stale). The key distinction: 'unavailable' does not claim the data is
        # stale, only that we cannot check.
        for w in result["warnings"]:
            if w.get("source") in ("daily_prices", "financial_metrics", "industry_classification"):
                # Must NOT be the old permanent false-positive 'unknown'.
                assert w.get("latest_date") != "unknown" or w.get("severity") != "UNKNOWN", (
                    f"source {w.get('source')} permanently marked UNKNOWN — disease G not fixed; "
                    f"the date-column query fails on the real (key,value,expires_at) schema"
                )


class TestApplyFreshnessConfidencePenalty:
    def test_no_penalty_when_fresh(self) -> None:
        recs = [{"ticker": "000001", "confidence": 85}]
        freshness = {"fresh": True, "warnings": []}
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == 85
        assert "confidence_penalty" not in result[0]

    def test_high_severity_penalty(self) -> None:
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "HIGH", "source": "daily_prices"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(70.0, abs=0.1)
        assert result[0]["confidence_penalty"] == 0.3

    def test_medium_severity_penalty(self) -> None:
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "MEDIUM", "source": "financial_metrics"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(85.0, abs=0.1)

    def test_low_severity_penalty(self) -> None:
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "LOW", "source": "industry"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(95.0, abs=0.1)

    def test_worst_severity_wins(self) -> None:
        """When multiple warnings, the worst severity determines penalty."""
        recs = [{"ticker": "000001", "confidence": 100}]
        freshness = {
            "fresh": False,
            "warnings": [
                {"severity": "LOW", "source": "a"},
                {"severity": "HIGH", "source": "b"},
                {"severity": "MEDIUM", "source": "c"},
            ],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        assert result[0]["confidence"] == pytest.approx(70.0, abs=0.1)

    def test_empty_recommendations(self) -> None:
        freshness = {"fresh": False, "warnings": [{"severity": "HIGH"}]}
        result = apply_freshness_confidence_penalty([], freshness)
        assert result == []

    def test_confidence_zero_preserved_not_silently_overwritten_r96(self) -> None:
        """R96 (Bug Hunt, R68/R69 falsy-zero 同族): confidence=0.0 是合法值
        (agent error/fallback 明确输出 0.0 = "完全无信心", 见 ben_graham/bill_ackman/
        cathie_wood/michael_burry/mohnish_pabrai/aswath_damodaran 的 confidence=0.0 fallback)。

        此前 ``rec.get("confidence", 100) or 100`` 的 ``or`` 短路把 0.0 静默覆盖为 100
        (满信心), 然后 ``100 * penalty`` 让一个"完全无信心"的 agent 输出变成"高信心推荐",
        直接破坏"更高确信"目标。修复后 0.0 必须保留 (仅施加 penalty)。

        与 R68 (_resolve_trade_pnl break-even PnL) / R69 (unit-interval metric overrides)
        完全同型: falsy-zero 被 ``or`` 静默丢弃。
        """
        # confidence=0.0 (agent 明确说"完全无信心"), HIGH severity penalty (×0.7)
        recs = [{"ticker": "000001", "confidence": 0.0}]
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "HIGH", "source": "daily_prices"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        # 0.0 必须保留 (0.0 * 0.7 = 0.0), 不得被 or 100 改成 70.0
        assert result[0]["confidence"] == pytest.approx(0.0, abs=0.01), f"confidence=0.0 应保留为 0.0 (合法'完全无信心'), 不得被 falsy-zero `or 100` " f"静默覆盖为满信心。实际: {result[0]['confidence']}"

    def test_confidence_missing_defaults_to_100_r96(self) -> None:
        """对照组: missing confidence 字段应走默认 100 (满信心, 与历史行为一致)。

        修复必须区分"字段缺失"(→ 默认 100) vs "字段=0.0"(→ 保留 0.0)。
        用显式 presence-check (``raw is not None``), 不用 ``or``。
        用 stale freshness 进入 penalty 循环 (fresh 路径提前 return 不写字段)。
        """
        recs = [{"ticker": "000001"}]  # 无 confidence 字段
        freshness = {
            "fresh": False,
            "warnings": [{"severity": "HIGH", "source": "daily_prices"}],
        }
        result = apply_freshness_confidence_penalty(recs, freshness)
        # missing → 默认 100, HIGH penalty ×0.7 → 70.0
        assert result[0]["confidence"] == pytest.approx(70.0, abs=0.1), "missing confidence 应默认 100, 然后 HIGH penalty ×0.7 = 70.0"


class TestRenderFreshnessSummary:
    def test_fresh_summary_text(self) -> None:
        summary = _render_freshness_summary(True, [])
        assert "通过" in summary

    def test_stale_summary_shows_max_30_percent_penalty(self) -> None:
        """Regression: the summary line must state the real max penalty (30%),
        not the confused '70%' that (1.0-0.3)*100 produced.
        HIGH severity → confidence × 0.7 → at most 30% loss."""
        warnings = [
            {
                "severity": "HIGH",
                "label": "行情数据",
                "latest_date": "2026-06-10",
                "stale_days": 3,
                "max_stale_days": 1,
            }
        ]
        summary = _render_freshness_summary(False, warnings)
        assert "最高 30%" in summary
        assert "70%" not in summary

    def test_stale_summary_discloses_penalty_does_not_affect_composite(self) -> None:
        """autodev-6 / disease F (silent-display): the freshness penalty acts on
        rec.confidence, which composite_score (the actual ranking / BUY-gate key)
        does NOT read. The old line "已按最严重等级施加惩罚" implied the penalty
        reduces recommendation confidence in the decision, but it has zero effect
        on composite_score / ordering / BUY verdict. The summary must disclose
        this scope limit so the operator is not misled.

        Reproducer: composite_score = score_b + adjustments; confidence is never
        read (verified: grep confidence src/screening/composite_score.py shows
        only docstrings). apply_freshness_confidence_penalty is called only in
        decision_flow on in-memory recs; compute_composite_scores re-reads the
        report from disk. So the penalty is cosmetic w.r.t. the decision basis.
        """
        warnings = [
            {
                "severity": "HIGH",
                "label": "行情数据",
                "latest_date": "2026-06-10",
                "stale_days": 3,
                "max_stale_days": 1,
            }
        ]
        summary = _render_freshness_summary(False, warnings)
        # The penalty line must honestly state it does NOT change composite_score
        # / ordering / BUY verdict (the actual decision basis).
        assert "不影响" in summary or "不影响排序" in summary or "不传导" in summary
