"""P0-5 智能自选池 — 单元测试 (≥15)。

覆盖:
  1. 添加标的
  2. 重复添加 → 不报错, 更新 tags / note, 保留 added_at / score_history
  3. 移除标的
  4. 移除不存在的标的 → 返回 False
  5. 列出全部
  6. 按 tag 过滤
  7. update_score 写入历史
  8. get_score_history 升序 + lookback 截取
  9. filter_valid_tickers 部分有效
  10. JSON 文件不存在 → 自动创建空自选池
  11. JSON 文件损坏 → 优雅降级
  12. WatchlistEntry to_dict / from_dict 圆环
  13. tags 列表去重 + 去空白
  14. score_history 自动截断到 MAX_SCORE_HISTORY_DAYS
  15. CLI smoke test (--watchlist-list 退出码 0)
  16. update_score 同日覆盖
  17. update_score 对不在自选池的 ticker 静默忽略
  18. format_watchlist_status 表格输出含必要字段
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.screening.watchlist import (
    DEFAULT_WATCHLIST_PATH,
    format_watchlist_status,
    MAX_SCORE_HISTORY_DAYS,
    Watchlist,
    WatchlistEntry,
)

# ============================================================================
# 1. 添加 / 重复添加 / 移除
# ============================================================================


def test_add_new_ticker(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    entry = wl.add("000001", "平安银行", tags=["银行", "高股息"], note="关注业绩拐点")

    assert entry.ticker == "000001"
    assert entry.name == "平安银行"
    assert entry.tags == ["银行", "高股息"]
    assert entry.note == "关注业绩拐点"
    assert len(entry.added_at) == 10  # YYYY-MM-DD


def test_add_duplicate_ticker_updates_tags_and_note(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    first = wl.add("000001", "平安银行", tags=["银行"], note="原备注")
    original_added = first.added_at
    # 给原条目写一条历史避免被覆盖丢失
    wl.update_score("000001", score=0.5, signal="buy", date="2026-06-01")

    second = wl.add("000001", "平安银行", tags=["银行", "高股息"], note="新备注")
    assert second.tags == ["银行", "高股息"]
    assert second.note == "新备注"
    assert second.added_at == original_added  # added_at 不应被覆盖
    # 历史保留
    assert len(second.score_history) == 1


def test_remove_existing_ticker(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    ok = wl.remove("000001")
    assert ok is True
    assert wl.get("000001") is None


def test_remove_missing_ticker_returns_false(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    ok = wl.remove("999999")
    assert ok is False


# ============================================================================
# 2. list / 按 tag 过滤
# ============================================================================


def test_list_all_entries(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行", tags=["银行"])
    wl.add("300750", "宁德时代", tags=["新能源"])
    wl.add("600519", "贵州茅台", tags=["白酒"])
    entries = wl.list()
    assert len(entries) == 3
    tickers = {e.ticker for e in entries}
    assert tickers == {"000001", "300750", "600519"}


def test_list_filtered_by_tag(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行", tags=["银行", "高股息"])
    wl.add("600036", "招商银行", tags=["银行"])
    wl.add("300750", "宁德时代", tags=["新能源"])

    banks = wl.list(tag="银行")
    assert {e.ticker for e in banks} == {"000001", "600036"}

    dividend = wl.list(tag="高股息")
    assert {e.ticker for e in dividend} == {"000001"}

    nothing = wl.list(tag="不存在")
    assert nothing == []


# ============================================================================
# 3. update_score / get_score_history
# ============================================================================


def test_update_score_appends_to_history(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    wl.update_score("000001", score=0.45, signal="watch", date="2026-06-05")
    wl.update_score("000001", score=0.55, signal="buy", date="2026-06-06")
    wl.update_score("000001", score=0.60, signal="strong_buy", date="2026-06-07")

    entry = wl.get("000001")
    assert entry is not None
    assert len(entry.score_history) == 3
    assert entry.score_history[-1]["signal"] == "strong_buy"


def test_get_score_history_returns_sorted_with_lookback(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    # 故意乱序写入
    wl.update_score("000001", score=0.6, signal="buy", date="2026-06-07")
    wl.update_score("000001", score=0.4, signal="watch", date="2026-06-05")
    wl.update_score("000001", score=0.5, signal="watch", date="2026-06-06")

    history = wl.get_score_history("000001", lookback_days=30)
    # 升序
    assert [item["date"] for item in history] == ["2026-06-05", "2026-06-06", "2026-06-07"]

    # lookback=2 应只返回最近 2 天
    last2 = wl.get_score_history("000001", lookback_days=2)
    assert [item["date"] for item in last2] == ["2026-06-06", "2026-06-07"]


def test_update_score_same_day_overrides(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    wl.update_score("000001", score=0.3, signal="watch", date="2026-06-07")
    wl.update_score("000001", score=0.55, signal="buy", date="2026-06-07")

    history = wl.get_score_history("000001")
    assert len(history) == 1
    assert history[0]["score"] == 0.55
    assert history[0]["signal"] == "buy"


def test_update_score_missing_ticker_silently_ignored(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    # Should not raise and should not add a phantom entry
    wl.update_score("999999", score=0.5, signal="buy")
    assert wl.get("999999") is None
    assert len(wl) == 0


# ============================================================================
# 4. filter_valid_tickers
# ============================================================================


def test_filter_valid_tickers_partial_match(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    wl.add("300750", "宁德时代")

    candidates = ["999999", "000001", "300750", "AAPL"]
    filtered = wl.filter_valid_tickers(candidates)
    # 保留原顺序, 去掉无效项
    assert filtered == ["000001", "300750"]


def test_filter_valid_tickers_empty_candidates(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    assert wl.filter_valid_tickers([]) == []


# ============================================================================
# 5. 文件不存在 / 损坏
# ============================================================================


def test_missing_file_creates_empty_watchlist(tmp_path: Path) -> None:
    path = tmp_path / "non_existent.json"
    assert not path.exists()
    wl = Watchlist(path)
    assert len(wl) == 0
    assert wl.list() == []
    # 此时未写文件 (load 不应当创建文件)
    assert not path.exists()
    # 首次 add 时才会创建
    wl.add("000001", "平安银行")
    assert path.exists()


def test_corrupted_file_degrades_gracefully(tmp_path: Path) -> None:
    path = tmp_path / "corrupted.json"
    path.write_text("not valid json{{{", encoding="utf-8")
    wl = Watchlist(path)
    assert len(wl) == 0
    # 后续操作仍可用 — 写入新数据会覆盖损坏文件
    wl.add("000001", "平安银行")
    assert len(wl) == 1
    # 重新加载验证持久化成功
    wl2 = Watchlist(path)
    assert wl2.get("000001") is not None


def test_file_missing_watchlist_key_degrades_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "bad_shape.json"
    path.write_text(json.dumps({"unrelated": "data"}), encoding="utf-8")
    wl = Watchlist(path)
    assert len(wl) == 0


# ============================================================================
# 6. WatchlistEntry to_dict / from_dict 圆环
# ============================================================================


def test_watchlist_entry_to_from_dict_roundtrip() -> None:
    original = WatchlistEntry(
        ticker="000001",
        name="平安银行",
        added_at="2026-06-07",
        tags=["银行", "高股息"],
        note="关注业绩拐点",
        score_history=[{"date": "2026-06-07", "score": 0.45, "signal": "watch"}],
    )
    serialized = original.to_dict()
    restored = WatchlistEntry.from_dict(serialized)
    assert restored.ticker == original.ticker
    assert restored.name == original.name
    assert restored.added_at == original.added_at
    assert restored.tags == original.tags
    assert restored.note == original.note
    assert restored.score_history == original.score_history


def test_watchlist_entry_from_dict_handles_missing_fields() -> None:
    entry = WatchlistEntry.from_dict({"ticker": "000001", "name": "平安银行"})
    assert entry.ticker == "000001"
    assert entry.tags == []
    assert entry.note == ""
    assert entry.score_history == []
    # added_at 兜底为今天
    assert len(entry.added_at) == 10


# ============================================================================
# 7. tags 去重
# ============================================================================


def test_tags_are_deduplicated_on_add(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    # 含重复 / 空白
    entry = wl.add("000001", "平安银行", tags=["银行", "银行", " ", "高股息", "  高股息  "])
    # 顺序保留, 去重 + 去空白; "  高股息  " 与 "高股息" 视为相同 (strip)
    assert entry.tags == ["银行", "高股息"]


# ============================================================================
# 8. score_history 自动截断
# ============================================================================


def test_score_history_truncates_to_max_days(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    # 写入 35 天历史 (超过 MAX_SCORE_HISTORY_DAYS=30)
    for day in range(1, 36):
        date_str = f"2026-05-{day:02d}" if day <= 31 else f"2026-06-{day - 31:02d}"
        wl.update_score("000001", score=day * 0.01, signal="watch", date=date_str)

    history = wl.get_score_history("000001", lookback_days=100)
    assert len(history) == MAX_SCORE_HISTORY_DAYS
    # 最早的应被截断, 保留最近 30 天
    dates = [item["date"] for item in history]
    assert dates == sorted(dates)


# ============================================================================
# 9. 持久化往返
# ============================================================================


def test_persistence_round_trip(tmp_path: Path) -> None:
    """add / update_score / remove 后, 重新加载应保留状态。"""
    path = tmp_path / "wl.json"
    wl1 = Watchlist(path)
    wl1.add("000001", "平安银行", tags=["银行"], note="关注")
    wl1.add("300750", "宁德时代", tags=["新能源"])
    wl1.update_score("000001", score=0.45, signal="watch", date="2026-06-07")
    wl1.remove("300750")

    # 重新加载
    wl2 = Watchlist(path)
    assert len(wl2) == 1
    entry = wl2.get("000001")
    assert entry is not None
    assert entry.tags == ["银行"]
    assert entry.note == "关注"
    assert len(entry.score_history) == 1
    assert entry.score_history[0]["score"] == 0.45


# ============================================================================
# 10. format_watchlist_status
# ============================================================================


def test_format_watchlist_status_basic(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行", tags=["银行"])
    wl.add("300750", "宁德时代", tags=["新能源"])
    wl.update_score("000001", score=0.45, signal="watch")
    # 300750 无评分

    output = format_watchlist_status(wl)
    assert "智能自选池状态" in output
    assert "000001" in output
    assert "平安银行" in output
    assert "300750" in output
    assert "宁德时代" in output
    assert "+0.45" in output


def test_format_watchlist_status_empty(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    output = format_watchlist_status(wl)
    assert "自选池为空" in output


def test_format_watchlist_status_with_consecutive_info(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    wl.update_score("000001", score=0.45, signal="watch")
    consecutive = {"000001": {"consecutive_days": 3, "status": "consecutive_3plus"}}
    output = format_watchlist_status(wl, consecutive_lookup=consecutive)
    assert "持续 3 天推荐" in output


# ============================================================================
# 11. CLI smoke test (--watchlist-list)
# ============================================================================


def test_cli_watchlist_list_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """运行 `python -m src.main --watchlist-list` 应以退出码 0 结束。

    将 cwd 设为 tmp_path 避免污染真实 ``data/watchlist.json``。
    """
    monkeypatch.chdir(tmp_path)

    repo_root = Path(__file__).resolve().parents[1]
    # 使用当前解释器调用 src/main.py
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--watchlist-list"],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    # 不应崩溃
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    # 输出应包含自选池表头
    combined = result.stdout + result.stderr
    assert "自选池" in combined or "watchlist" in combined.lower()


# ============================================================================
# 12. __contains__ / __len__ / all_tickers / get
# ============================================================================


def test_dunder_helpers(tmp_path: Path) -> None:
    wl = Watchlist(tmp_path / "wl.json")
    wl.add("000001", "平安银行")
    wl.add("300750", "宁德时代")
    assert len(wl) == 2
    assert "000001" in wl
    assert "999999" not in wl
    assert wl.get("000001") is not None
    assert wl.get("999999") is None
    assert wl.all_tickers() == ["000001", "300750"]


# ============================================================================
# 13. 默认路径常量
# ============================================================================


def test_default_path_is_data_watchlist_json() -> None:
    """文档约定默认路径为 data/watchlist.json。"""
    assert str(DEFAULT_WATCHLIST_PATH) == str(Path("data/watchlist.json"))


# ============================================================================
# 14. update_watchlist_from_screening 集成
# ============================================================================


def test_update_watchlist_from_screening_scores_watched_tickers(tmp_path: Path) -> None:
    """update_watchlist_from_screening 应仅对自选池中的标的写入评分。"""
    from src.main import update_watchlist_from_screening

    wl_path = tmp_path / "wl.json"
    wl = Watchlist(wl_path)
    wl.add("000001", "平安银行")
    wl.add("300750", "宁德时代")

    report_payload = {
        "date": "20260607",
        "recommendations": [
            {"ticker": "000001", "score_b": 0.45, "decision": "watch", "consecutive_days": 2},
            {"ticker": "300750", "score_b": 0.55, "decision": "buy", "consecutive_days": 3},
            # 这个不在自选池, 应被忽略
            {"ticker": "999999", "score_b": 0.30, "decision": "watch"},
        ],
    }

    summary = update_watchlist_from_screening(report_payload, watchlist_path=wl_path)
    assert summary["scored_count"] == 2
    assert len(summary["top_picks"]) == 2
    # 按 score 降序
    assert summary["top_picks"][0]["ticker"] == "300750"
    assert summary["top_picks"][1]["ticker"] == "000001"

    # 重新加载验证持久化
    wl2 = Watchlist(wl_path)
    e1 = wl2.get("000001")
    assert e1 is not None
    assert e1.score_history[-1]["score"] == 0.45
    assert e1.score_history[-1]["signal"] == "watch"
    # 日期已规范化为 YYYY-MM-DD
    assert e1.score_history[-1]["date"] == "2026-06-07"
    # 999999 不应误入自选池
    assert wl2.get("999999") is None


def test_update_watchlist_from_screening_empty_watchlist(tmp_path: Path) -> None:
    """自选池为空时, 应直接返回 scored_count=0 而不报错。"""
    from src.main import update_watchlist_from_screening

    wl_path = tmp_path / "wl.json"
    Watchlist(wl_path)  # 空自选池

    report_payload = {
        "date": "20260607",
        "recommendations": [{"ticker": "000001", "score_b": 0.45, "decision": "watch"}],
    }
    summary = update_watchlist_from_screening(report_payload, watchlist_path=wl_path)
    assert summary == {"scored_count": 0, "top_picks": []}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
