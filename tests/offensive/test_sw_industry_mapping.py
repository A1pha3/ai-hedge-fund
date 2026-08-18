"""SW L1 行业映射两层加载 + 落盘 (对抗审查 BUG-2, 2026-08-17).

背景: --daily-action BTST 条件3 的票→行业映射此前只来自候选池快照并集,
涨停注入票 (从未进池) 拿不到行业 → 被「行业缺失=miss」静默过滤
(2026-08-14 涨停 62 只中 15 只死在该缺口)。修复: --auto 落盘全市场
SW 映射 (cache_refresh._persist_sw_industry_snapshot), daily_action
优先读文件、候选池快照兜底。
"""

from __future__ import annotations

import json

from src.screening.offensive.cache_refresh import _persist_sw_industry_snapshot
from src.screening.offensive.daily_action import _load_ticker_to_industry_from_snapshots


def _write_sw_snapshot(snapshot_dir, mapping: dict, *, signal_date: str = "20260817") -> None:
    payload = {
        "observed_at": "2026-08-17T08:00:00+00:00",
        "signal_date": signal_date,
        "mapping": mapping,
    }
    (snapshot_dir / "sw_industry_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _write_pool_snapshot(snapshot_dir, name: str, records: list[dict]) -> None:
    (snapshot_dir / name).write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )


def test_sw_file_layer_covers_injected_tickers(tmp_path):
    """SW 文件层把从未进候选池的注入票纳入行业映射 (修复的核心断言)."""
    _write_sw_snapshot(tmp_path, {"002628.SZ": "建筑装饰", "603186.SH": "电子"})
    _write_pool_snapshot(
        tmp_path, "candidate_pool_20260814.json", [{"ticker": "600487.SH", "industry": "通信"}]
    )

    result = _load_ticker_to_industry_from_snapshots(
        ["002628", "603186", "600487"], snapshot_dir=tmp_path
    )
    assert result == {"002628": "建筑装饰", "603186": "电子", "600487": "通信"}


def test_sw_layer_takes_precedence_over_pool_snapshots(tmp_path):
    """同票两层都有时 SW 文件优先 (全市场、更新鲜)."""
    _write_sw_snapshot(tmp_path, {"600487.SH": "通信"})
    _write_pool_snapshot(
        tmp_path, "candidate_pool_20260814.json", [{"ticker": "600487.SH", "industry": "旧行业"}]
    )

    result = _load_ticker_to_industry_from_snapshots(["600487"], snapshot_dir=tmp_path)
    assert result == {"600487": "通信"}


def test_missing_or_corrupt_sw_file_falls_back_to_pool_snapshots(tmp_path):
    """SW 文件缺失/损坏 → 行为回到修复前 (纯快照层), 不抛异常."""
    _write_pool_snapshot(
        tmp_path, "candidate_pool_20260814.json", [{"ticker": "600487.SH", "industry": "通信"}]
    )

    # 缺失
    assert _load_ticker_to_industry_from_snapshots(["600487"], snapshot_dir=tmp_path) == {
        "600487": "通信"
    }
    # 损坏 JSON
    (tmp_path / "sw_industry_latest.json").write_text("not-json{", encoding="utf-8")
    assert _load_ticker_to_industry_from_snapshots(["600487"], snapshot_dir=tmp_path) == {
        "600487": "通信"
    }
    # 结构异常 (mapping 非 dict)
    (tmp_path / "sw_industry_latest.json").write_text(
        json.dumps({"mapping": ["not", "a", "dict"]}), encoding="utf-8"
    )
    assert _load_ticker_to_industry_from_snapshots(["600487"], snapshot_dir=tmp_path) == {
        "600487": "通信"
    }


def test_persist_sw_industry_snapshot_writes_code6_mapping(tmp_path):
    target = tmp_path / "sw_industry_latest.json"

    ok = _persist_sw_industry_snapshot(
        {"603186.SH": "电子", "invalid": "", "002628.SZ": "建筑装饰"},
        "20260817",
        snapshot_dir=tmp_path,
    )
    assert ok is True
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["signal_date"] == "20260817"
    assert payload["mapping"] == {"603186": "电子", "002628": "建筑装饰"}  # code6 键, 空行业剔除


def test_persist_sw_industry_snapshot_is_advisory_on_failure(tmp_path, monkeypatch):
    """落盘失败 (IO 错误) 只返回 False, 绝不抛 — 刷新主流程不受影响."""

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("src.screening.offensive.cache_refresh.atomic_write_json", _boom)
    assert (
        _persist_sw_industry_snapshot({"603186.SH": "电子"}, "20260817", snapshot_dir=tmp_path)
        is False
    )


# --- 名称校验 (第二遍对抗审查): 防 API 名称与 industry_index_cache 键名漂移 ---


def test_persist_drops_unknown_industry_names_and_warns(tmp_path, caplog):
    """未知行业名的票不落盘 (快照层兜底), 已知名正常写入, 并告警计数."""
    import logging as _logging

    from src.screening.offensive.cache_refresh import _persist_sw_industry_snapshot

    with caplog.at_level(_logging.WARNING, logger="src.screening.offensive.cache_refresh"):
        ok = _persist_sw_industry_snapshot(
            {"603186.SH": "电子", "999999.SH": "新神秘行业", "002628.SZ": "建筑装饰"},
            "20260817",
            snapshot_dir=tmp_path,
            known_industries={"电子", "建筑装饰"},
        )
    assert ok is True
    payload = json.loads((tmp_path / "sw_industry_latest.json").read_text(encoding="utf-8"))
    assert payload["mapping"] == {"603186": "电子", "002628": "建筑装饰"}
    assert any("未知行业名 1 只" in r.message for r in caplog.records)


def test_persist_without_known_set_skips_validation(tmp_path):
    """known_industries=None (校验集不可用) → 不校验, 全量落盘."""
    from src.screening.offensive.cache_refresh import _persist_sw_industry_snapshot

    ok = _persist_sw_industry_snapshot(
        {"999999.SH": "任意名"}, "20260817", snapshot_dir=tmp_path, known_industries=None
    )
    assert ok is True
    payload = json.loads((tmp_path / "sw_industry_latest.json").read_text(encoding="utf-8"))
    assert payload["mapping"] == {"999999": "任意名"}


def test_load_known_industry_names_reads_codes_json(tmp_path):
    from src.screening.offensive.cache_refresh import _load_known_industry_names

    codes = tmp_path / "_industry_codes.json"
    codes.write_text(json.dumps({"801080.SI": "电子", "801050.SI": "有色金属"}), encoding="utf-8")
    assert _load_known_industry_names(tmp_path) == {"电子", "有色金属"}
    # 缺失/损坏 → None (不校验), 绝不抛
    assert _load_known_industry_names(tmp_path / "nope") is None
    codes.write_text("bad{", encoding="utf-8")
    assert _load_known_industry_names(tmp_path) is None
