"""智能自选池 — 用户标记关注的股票，每日自动更新评分和信号 (P0-5)。

设计目标:
  - 简单 JSON 文件持久化, 不引入数据库依赖。
  - 失败优雅降级: 文件不存在自动创建; 文件损坏返回空自选池而非崩溃。
  - 增量数据: ``score_history`` 自动截断至最近 N 天 (默认 30) 避免无限增长。
  - 与 P0-6 ``consecutive_recommendation`` 协同: 自选池状态展示连续推荐天数。

主入口:
  - ``WatchlistEntry``: 单标的元数据 (ticker / name / tags / note / score_history)
  - ``Watchlist``: 管理器 — add / remove / list / update_score / get_score_history /
    filter_valid_tickers / save_atomic / load
  - 顶层常量 ``DEFAULT_WATCHLIST_PATH`` / ``MAX_SCORE_HISTORY_DAYS``
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WATCHLIST_PATH: Path = Path("data/watchlist.json")
MAX_SCORE_HISTORY_DAYS: int = 30


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class WatchlistEntry:
    """自选池中的单只股票。

    Fields:
        ticker: 6 位 A 股代码 (e.g. "000001") 或美股 ticker (e.g. "AAPL")
        name: 股票中文/英文名 (e.g. "平安银行")
        added_at: 加入日期, 格式 YYYY-MM-DD
        tags: 用户自定义标签列表 (e.g. ["银行", "高股息"]). **去重保序**。
        note: 用户备注 (可选, 默认空字符串)
        score_history: 评分历史 [{"date": "2026-06-07", "score": 0.45, "signal": "watch"}, ...]
            自动截断至最近 ``MAX_SCORE_HISTORY_DAYS`` 天。
    """

    ticker: str
    name: str
    added_at: str
    tags: list[str] = field(default_factory=list)
    note: str = ""
    score_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON-safe dict。"""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "added_at": self.added_at,
            "tags": list(self.tags),
            "note": self.note,
            "score_history": list(self.score_history),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WatchlistEntry:
        """从 dict 反序列化, 缺失字段使用默认值, 容忍异常 tags 类型。"""
        raw_tags = payload.get("tags") or []
        if not isinstance(raw_tags, list):
            raw_tags = []
        # 去重保序 + 强制 str
        seen: set[str] = set()
        tags: list[str] = []
        for tag in raw_tags:
            tag_str = str(tag).strip()
            if tag_str and tag_str not in seen:
                seen.add(tag_str)
                tags.append(tag_str)

        raw_history = payload.get("score_history") or []
        if not isinstance(raw_history, list):
            raw_history = []
        history = [item for item in raw_history if isinstance(item, dict)]

        return cls(
            ticker=str(payload.get("ticker", "")).strip(),
            name=str(payload.get("name", "")).strip(),
            added_at=str(payload.get("added_at") or datetime.now().strftime("%Y-%m-%d")),
            tags=tags,
            note=str(payload.get("note") or ""),
            score_history=history,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dedupe_tags(tags: list[str] | None) -> list[str]:
    """去重保序 + 去空白 + 强制 str。"""
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        tag_str = str(tag).strip()
        if tag_str and tag_str not in seen:
            seen.add(tag_str)
            out.append(tag_str)
    return out


def _today_iso() -> str:
    """返回今天日期, 格式 YYYY-MM-DD。"""
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Watchlist manager
# ---------------------------------------------------------------------------


class Watchlist:
    """自选池管理器 — JSON 文件持久化。

    所有读写操作通过 ``load()`` / ``_save()`` 中介:
      - 加载: 文件不存在 -> 创建空自选池; 损坏 -> 警告并返回空自选池。
      - 保存: 写临时文件 + ``os.replace`` 原子替换, 防止部分写入。

    Usage:
        wl = Watchlist()                          # 默认路径 data/watchlist.json
        wl = Watchlist(Path("custom/path.json"))  # 自定义路径
        entry = wl.add("000001", "平安银行", tags=["银行"])
        wl.update_score("000001", score=0.45, signal="buy")
        entries = wl.list(tag="银行")
        ok = wl.remove("000001")
    """

    def __init__(self, path: Path | str = DEFAULT_WATCHLIST_PATH) -> None:
        self.path: Path = Path(path)
        self._entries: dict[str, WatchlistEntry] = {}
        self.load()

    # -- persistence --

    def load(self) -> None:
        """从 ``self.path`` 加载自选池。文件不存在 -> 空; 损坏 -> 警告 + 空。"""
        self._entries = {}
        if not self.path.exists():
            logger.debug("[Watchlist] 文件不存在, 使用空自选池: %s", self.path)
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[Watchlist] 加载失败, 使用空自选池 (%s): %s", self.path, exc)
            return
        watchlist_section = payload.get("watchlist") if isinstance(payload, dict) else None
        if not isinstance(watchlist_section, dict):
            logger.warning("[Watchlist] 文件结构异常 (缺 watchlist 字段或非 dict): %s", self.path)
            return
        for ticker, payload_entry in watchlist_section.items():
            if not isinstance(payload_entry, dict):
                continue
            try:
                entry = WatchlistEntry.from_dict({**payload_entry, "ticker": ticker})
                if entry.ticker:
                    self._entries[entry.ticker] = entry
            except Exception as exc:  # pragma: no cover — 双重防御
                logger.warning("[Watchlist] 解析条目失败 ticker=%s: %s", ticker, exc)

    def _save(self) -> None:
        """原子保存到 ``self.path`` (临时文件 + ``os.replace``)。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"watchlist": {ticker: entry.to_dict() for ticker, entry in sorted(self._entries.items())}}
        # 写临时文件 (同目录确保 os.replace 在同一 mount point)
        tmp_dir = str(self.path.parent)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=tmp_dir, delete=False, suffix=".tmp") as tmp:
            tmp_path = tmp.name
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    # -- mutators --

    def add(self, ticker: str, name: str, tags: list[str] | None = None, note: str = "") -> WatchlistEntry:
        """添加标的到自选池。已存在则更新 ``name`` / ``tags`` / ``note`` 但保留 ``added_at`` 与 ``score_history``。"""
        ticker = str(ticker).strip()
        if not ticker:
            raise ValueError("ticker 不能为空")
        name = str(name).strip()
        deduped = _dedupe_tags(tags)

        existing = self._entries.get(ticker)
        if existing is None:
            entry = WatchlistEntry(
                ticker=ticker,
                name=name,
                added_at=_today_iso(),
                tags=deduped,
                note=str(note or ""),
            )
            self._entries[ticker] = entry
        else:
            existing.name = name or existing.name
            existing.tags = deduped if deduped else existing.tags
            if note:
                existing.note = str(note)
            entry = existing
        self._save()
        return entry

    def remove(self, ticker: str) -> bool:
        """从自选池移除。返回是否成功移除 (False 表示不存在)。"""
        ticker = str(ticker).strip()
        if ticker in self._entries:
            del self._entries[ticker]
            self._save()
            return True
        return False

    def update_score(self, ticker: str, score: float, signal: str, date: str | None = None) -> None:
        """更新某标的的最新评分和信号。

        - 同日重复调用会覆盖当日记录 (避免重复)。
        - 自动按 ``date`` 升序排序并截断至最近 ``MAX_SCORE_HISTORY_DAYS`` 天。
        - 若 ticker 不在自选池中静默忽略 (避免误增条目)。
        """
        ticker = str(ticker).strip()
        entry = self._entries.get(ticker)
        if entry is None:
            return
        date_str = str(date or _today_iso())
        # 移除同日已有记录, 后续 append 实现覆盖
        entry.score_history = [item for item in entry.score_history if str(item.get("date", "")) != date_str]
        entry.score_history.append({
            "date": date_str,
            "score": float(score) if score is not None else 0.0,
            "signal": str(signal or ""),
        })
        # 排序 + 截断
        entry.score_history.sort(key=lambda item: str(item.get("date", "")))
        if len(entry.score_history) > MAX_SCORE_HISTORY_DAYS:
            entry.score_history = entry.score_history[-MAX_SCORE_HISTORY_DAYS:]
        self._save()

    # -- read-only --

    def list(self, tag: str | None = None) -> list[WatchlistEntry]:
        """列出所有自选标的, 可按 ``tag`` 过滤。

        Returns:
            按 ``added_at`` 降序 (最新加入排在前) 的列表; 同日按 ticker 升序。
        """
        entries = list(self._entries.values())
        if tag:
            entries = [e for e in entries if tag in e.tags]
        entries.sort(key=lambda e: (e.added_at, e.ticker), reverse=False)
        # 最新加入在前
        entries.sort(key=lambda e: e.added_at, reverse=True)
        return entries

    def get_score_history(self, ticker: str, lookback_days: int = 30) -> list[dict[str, Any]]:
        """获取标的的评分历史 (按日期升序). lookback_days 截取尾部。"""
        ticker = str(ticker).strip()
        entry = self._entries.get(ticker)
        if entry is None:
            return []
        history = sorted(entry.score_history, key=lambda item: str(item.get("date", "")))
        if lookback_days <= 0:
            return []
        if lookback_days >= len(history):
            return list(history)
        return list(history[-lookback_days:])

    def filter_valid_tickers(self, candidates: list[str]) -> list[str]:
        """从候选列表中过滤出自选标的, 保留 ``candidates`` 的相对顺序。"""
        valid_set = set(self._entries.keys())
        seen: set[str] = set()
        out: list[str] = []
        for ticker in candidates or []:
            ticker_str = str(ticker).strip()
            if ticker_str in valid_set and ticker_str not in seen:
                seen.add(ticker_str)
                out.append(ticker_str)
        return out

    def get(self, ticker: str) -> WatchlistEntry | None:
        """按 ticker 取条目, 不存在返回 None。"""
        return self._entries.get(str(ticker).strip())

    def all_tickers(self) -> list[str]:
        """返回所有 ticker 的列表 (按字典序)。"""
        return sorted(self._entries.keys())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, ticker: object) -> bool:
        return str(ticker).strip() in self._entries


# ---------------------------------------------------------------------------
# CLI rendering helpers
# ---------------------------------------------------------------------------


def format_watchlist_status(
    watchlist: Watchlist,
    consecutive_lookup: dict[str, dict[str, Any]] | None = None,
) -> str:
    """格式化自选池最新评分表 (按 score 降序). 含 P0-6 连续推荐信息。

    Args:
        watchlist: ``Watchlist`` 实例
        consecutive_lookup: ``{ticker: {"consecutive_days": int, "status": str}}`` 映射
            供 ``--watchlist-status`` 展示「连续 N 天推荐」。可选。

    Returns:
        纯文本字符串 (无 ANSI 颜色, 便于测试与日志)。
    """
    entries = watchlist.list()
    total = len(entries)
    header = "━━━ 智能自选池状态 ━━━\n"
    if total == 0:
        return header + "自选池为空。使用 --watchlist-add 添加标的。\n"
    header += f"共 {total} 只关注标的\n\n"

    # 计算每只标的的最新 score / signal
    rows: list[tuple[WatchlistEntry, float | None, str | None]] = []
    for entry in entries:
        latest = entry.score_history[-1] if entry.score_history else None
        if latest:
            try:
                score_val: float | None = float(latest.get("score", 0.0))
            except (TypeError, ValueError):
                score_val = None
            signal_val: str | None = str(latest.get("signal", "")) or None
        else:
            score_val = None
            signal_val = None
        rows.append((entry, score_val, signal_val))

    # 排序: 有评分的优先, score 降序; 无评分的放最后
    rows.sort(key=lambda row: (0 if row[1] is not None else 1, -(row[1] or 0.0)))

    lines: list[str] = []
    for entry, score, signal in rows:
        ticker_label = f"{entry.ticker} {entry.name}"
        if score is None:
            score_str = "score_b:   —  "
            arrow = "—"
            signal_str = "无数据"
        else:
            score_str = f"score_b: {score:+.2f}"
            arrow = "↑" if score > 0.05 else "↓" if score < -0.05 else "—"
            signal_str = signal or "—"
        # 连续推荐信息
        consecutive_str = ""
        if consecutive_lookup:
            info = consecutive_lookup.get(entry.ticker) or {}
            days = int(info.get("consecutive_days", 0) or 0)
            status = str(info.get("status", "") or "")
            if days >= 3:
                consecutive_str = f"持续 {days} 天推荐"
            elif days == 2:
                consecutive_str = "连续 2 天推荐"
            elif days == 1:
                consecutive_str = "首次出现"
            elif status == "broken_streak":
                consecutive_str = "断点重启"
            else:
                consecutive_str = ""
        if not consecutive_str:
            consecutive_str = "无数据" if score is None else ""
        lines.append(f"  {ticker_label:<18} {score_str}  {arrow} 信号: {signal_str:<8} {consecutive_str}".rstrip())

    return header + "\n".join(lines) + "\n\n按 score_b 降序排列。\n"


__all__ = [
    "DEFAULT_WATCHLIST_PATH",
    "MAX_SCORE_HISTORY_DAYS",
    "WatchlistEntry",
    "Watchlist",
    "format_watchlist_status",
]
