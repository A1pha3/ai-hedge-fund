"""R107 Op1: v3 官方 Trial 只读观测面 (scripts/v3_trial_status.py) 的测试。

R105 入册的观测面缺口收口: 此前拼出 trial 图景需要 15+ 次手工 sqlite
查询 (spine enrollment / 双臂 decision reason / arms NAV / evidence
命名空间 / nightly 链)。本测试把 status 工具的事实面钉死在**真实官方栈
world** 上 (复用 test_trial_session_driver 的 _DriverWorld + live_candidates
夹具), 而不是伪造 JSON —— status 报告的每个数字都要能在驱动器真实
decide/advance 之后的台账里找到。

诚实边界 (与工具 docstring 一致):
- 工具只做 verbatim 披露, 不重推导 canonical ``classify_pair_session``
  语义 (frozen evaluator 职责) —— 测试只断言 per-arm 原始事实;
- 零写入: ``mode=ro`` 连接无法 checkpoint 也无法写主库, 字节级断言钉死;
- 缺库/空库是合法启动形态 (R37: decisions 缺失 → 首 decide 自建),
  per-section 披露 missing 而非整体失败; 损坏库 per-section 报 error
  不吞 (P2-1: 宽吞会假装没看到坏记录)。
"""

from __future__ import annotations

import gc
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.v3_trial_status import main as status_main
from test_trial_session_driver import (  # noqa: E402
    DECIDE_AT,
    SIGNAL_SESSION,
    TICKERS,
    _DriverWorld,
    _snapshot,
)


def _live_detect_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    """R103 live_candidates 同款 detect patch ( crib test_trial_session_driver )."""
    from src.screening.offensive.setups.base import DetectionResult
    from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

    def _detect(self, ticker: str, trade_date: str, context: dict) -> DetectionResult:
        prices = context.get("prices")
        if prices is None or len(prices) == 0:
            return DetectionResult(
                hit=False,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=0.0,
                invalidation_condition="",
                metadata={},
                degraded=False,
                degradation_reason="",
            )
        if float(prices.iloc[-1]["close"]) <= 10.0:
            return DetectionResult(
                hit=False,
                ticker=ticker,
                trade_date=trade_date,
                trigger_strength=0.0,
                invalidation_condition="",
                metadata={},
                degraded=False,
                degradation_reason="",
            )
        return DetectionResult(
            hit=True,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=0.9,
            invalidation_condition="",
            metadata={},
            degraded=False,
            degradation_reason="",
        )

    monkeypatch.setattr(BtstBreakoutSetup, "detect", _detect)


def _bars(session: date) -> dict[str, object]:
    from src.screening.offensive.v3.execution.lifecycle import DailyBar

    return {
        f"{ticker}.SZ": DailyBar(
            security_id=f"{ticker}.SZ",
            session=session,
            open_cents=1100,
            high_cents=1200,
            low_cents=1050,
            close_cents=1150,
            limit_up_cents=1320,
            limit_down_cents=880,
        )
        for ticker in TICKERS
    }


def _settle_world(world: _DriverWorld) -> None:
    """释放 world 持有的全部引擎引用, 让 WAL 确定性落盘 (R42 纪律)。"""
    world.stack = None  # type: ignore[assignment]
    world.driver = None  # type: ignore[assignment]
    gc.collect()
    gc.collect()


def _root_snapshot(root: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _status_json(*args: str) -> dict:
    """运行 status 工具并解析其 JSON 输出 (main 返回退出码, JSON 在 stdout)。"""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = status_main(list(args))
    assert code == 0, f"status main exited {code}: {buffer.getvalue()[:300]}"
    return json.loads(buffer.getvalue())

class TestStatusReportOnRealWorld:
    """真实官方栈 world 上的事实断言 (NO_SIGNAL 世界 + RUN 世界两变体)。"""

    def test_no_signal_world_reports_full_picture(self, tmp_path: Path) -> None:
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        t2 = SIGNAL_SESSION + timedelta(days=2)
        world.driver.advance_sessions(
            signal_session=SIGNAL_SESSION,
            through_session=t2,
            bars_by_session={
                s: _bars(s)
                for s in (
                    SIGNAL_SESSION,
                    SIGNAL_SESSION + timedelta(days=1),
                    t2,
                )
            },
            now=DECIDE_AT,
        )
        _settle_world(world)

        report = _status_json("--trial-root", str(world.root), "--json")

        # decisions: 两臂 no_trade, reason=NO_SIGNAL (R105 语义)
        decisions = report["decisions"]
        assert decisions["status"] == "ok"
        assert decisions["session_count"] == 1
        rows = decisions["sessions"][SIGNAL_SESSION.isoformat()]
        assert set(rows) == {"CHAMPION", "CHALLENGER"}
        for arm_row in rows.values():
            assert arm_row["kind"] == "no_trade"
            assert arm_row["reason"] == "NO_SIGNAL"

        # arms: NAV = genesis + 3 个驱动会话 (R106 glue 契约)
        for arm in ("champion", "challenger"):
            arm_section = report["arms"][arm]
            assert arm_section["status"] == "ok"
            assert arm_section["nav_observation_count"] == 4
            assert arm_section["open_position_count"] == 0
            assert arm_section["latest_nav"]["as_of"].startswith("2026-08-08")

        # spine: enrollment 非空 (R32 纪律的读面镜像)
        assert report["spine"]["status"] == "ok"
        assert report["spine"]["enrolled_count"] >= 1

        # evidence: regime 命名空间已播种
        assert report["evidence"]["evidence.sqlite3"]["status"] == "ok"
        namespaces = report["evidence"]["evidence.sqlite3"]["namespaces"]
        assert any(ns["namespace"] == "regime" for ns in namespaces)

        # headline rollup
        assert report["summary"]["decided_sessions"] == 1
        assert report["summary"]["no_trade_sessions"] == 1
        assert report["summary"]["run_sessions"] == 0

    def test_run_world_reports_lines_and_open_positions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _live_detect_patch(monkeypatch)
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        receipt = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        assert receipt.champion_status == "RUN"
        t1 = SIGNAL_SESSION + timedelta(days=1)
        world.driver.advance_sessions(
            signal_session=SIGNAL_SESSION,
            through_session=t1,
            bars_by_session={s: _bars(s) for s in (SIGNAL_SESSION, t1)},
            now=DECIDE_AT,
        )
        _settle_world(world)

        report = _status_json("--trial-root", str(world.root), "--json")

        rows = report["decisions"]["sessions"][SIGNAL_SESSION.isoformat()]
        for arm_row in rows.values():
            assert arm_row["kind"] == "run"
            assert arm_row["line_count"] >= 1

        for arm in ("champion", "challenger"):
            arm_section = report["arms"][arm]
            assert arm_section["open_position_count"] == 1
            assert arm_section["nav_observation_count"] == 3  # genesis + 2 会话
            position = arm_section["open_positions"][0]
            assert position["security_id"].startswith("300001")

        assert report["summary"]["run_sessions"] == 1

    def test_human_render_mentions_key_facts(self, tmp_path: Path) -> None:
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        _settle_world(world)

        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = status_main(["--trial-root", str(world.root)])
        assert code == 0
        rendered = buffer.getvalue()
        assert "NO_SIGNAL" in rendered
        assert "trial-regime-001" in rendered
        assert "champion" in rendered

    def test_zero_write_byte_level(self, tmp_path: Path) -> None:
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        _settle_world(world)

        before = _root_snapshot(world.root)
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            status_main(["--trial-root", str(world.root), "--json"])
        after = _root_snapshot(world.root)
        assert before == after, "status 工具必须字节级零写入"

    def test_idempotent_output(self, tmp_path: Path) -> None:
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        _settle_world(world)

        import contextlib
        import io

        outputs = []
        for _ in range(2):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                status_main(["--trial-root", str(world.root), "--json"])
            outputs.append(buffer.getvalue())
        assert outputs[0] == outputs[1]


class TestLegalStartupStatesAndDegradation:
    """缺库是合法启动形态 (per-section missing); 损坏库 per-section error 不吞。"""

    def test_empty_root_reports_missing_sections(self, tmp_path: Path) -> None:
        empty_root = tmp_path / "empty-root"
        empty_root.mkdir()
        # nightly 历史默认读仓库级 data/reports 全局路径 (R108b 环境泄漏修复):
        # 不显式钉进 tmp, 该测试在无 data/ 的隔离 slot 绿、在宿主 (真实夜间
        # 历史在位) 红 — 断言随运行机器漂移。显式指向空 tmp 恢复单测自足。
        report = _status_json(
            "--trial-root",
            str(empty_root),
            "--json",
            "--nightly-history",
            str(tmp_path / "no-such-nightly.jsonl"),
        )
        assert report["decisions"]["status"] == "missing"
        assert report["spine"]["status"] == "missing"
        assert report["arms"]["champion"]["status"] == "missing"
        assert report["evidence"]["evidence.sqlite3"]["status"] == "missing"
        assert report["nightly"]["status"] == "missing"

    def test_missing_root_is_typed_operator_error(self, tmp_path: Path) -> None:
        code = status_main(["--trial-root", str(tmp_path / "nope"), "--json"])
        assert code == 2

    def test_corrupt_decisions_db_degrades_per_section(
        self, tmp_path: Path
    ) -> None:
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        _settle_world(world)

        copy_root = tmp_path / "corrupt-copy"
        shutil.copytree(world.root, copy_root)
        (copy_root / "decisions.sqlite3").write_bytes(b"not a database at all")

        report = _status_json("--trial-root", str(copy_root), "--json")
        assert report["decisions"]["status"] == "error"
        # 其余 section 不被拖垮 (spine/evidence 是独立库)
        assert report["spine"]["status"] == "ok"
        assert report["arms"]["champion"]["status"] == "ok"

    def test_corrupt_decision_json_row_disclosed_not_crash(
        self, tmp_path: Path
    ) -> None:
        """损坏 decision_json 行: 该臂披露 unparseable, 同库健全臂不受影响。

        官方 store 的 trial_arm_decisions 是 append-only (UPDATE/DELETE 被
        不可变触发器拒绝 — store 纪律本身正确, 测试不应绕过), 故用合成
        最小库直测 status 工具的行级解析层: 同库内一臂损坏行 + 一臂健全行。"""
        import sqlite3

        root = tmp_path / "synthetic-root"
        root.mkdir()
        conn = sqlite3.connect(root / "decisions.sqlite3")
        conn.execute(
            """
            CREATE TABLE trial_arm_decisions (
                trial_id TEXT, signal_session TEXT, decision_cycle_id TEXT,
                arm TEXT, decision_json TEXT, created_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO trial_arm_decisions VALUES"
            " ('t', '2026-08-06', 'c1', 'CHAMPION', '{not json', '2026-08-06')"
        )
        conn.execute(
            "INSERT INTO trial_arm_decisions VALUES"
            " ('t', '2026-08-06', 'c1', 'CHALLENGER',"
            " '{\"reason\": \"NO_SIGNAL\"}', '2026-08-06')"
        )
        conn.commit()
        conn.close()

        report = _status_json("--trial-root", str(root), "--json")
        rows = report["decisions"]["sessions"]["2026-08-06"]
        assert rows["CHAMPION"]["kind"] == "unparseable"
        assert rows["CHALLENGER"]["kind"] == "no_trade"
        assert rows["CHALLENGER"]["reason"] == "NO_SIGNAL"


class TestNightlyTail:
    def test_nightly_tail_rendered(self, tmp_path: Path) -> None:
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        _settle_world(world)

        history = tmp_path / "nightly.jsonl"
        history.write_text(
            "\n".join(
                [
                    json.dumps(
                        {"date": "20260903", "stage": "fetch", "rc": 0, "detail": "ok"}
                    ),
                    json.dumps(
                        {
                            "date": "20260903",
                            "stage": "decide",
                            "rc": 0,
                            "detail": "ok",
                        }
                    ),
                    json.dumps(
                        {
                            "date": "20260903",
                            "stage": "advance",
                            "rc": 2,
                            "detail": "bar_set_missing",
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )
        report = _status_json(
            "--trial-root",
            str(world.root),
            "--json",
            "--nightly-history",
            str(history),
        )
        nightly = report["nightly"]
        assert nightly["status"] == "ok"
        assert nightly["last_date"] == "20260903"
        assert nightly["failed_stage_count"] == 1
        assert nightly["tail"][-1]["stage"] == "advance"


class TestAdversarialHardening:
    """R107 Op2: 对 Op1 的对抗性审查实锤三发现的回归钉死。

    P1 LEGAL_TERMINAL 是法律终态持仓 (bust/correction 后的终端态), 不是
    在持——canonical held 集是 repository.py:1693 的 ('OPEN','EXIT_PENDING')。
    P2 0 字节/空 schema 决策库是 R37 钉死的合法启动形态 (首 decide 自愈
    落表), 不得报 error (合法状态污名化为损坏)。
    P3 非空 -wal 下 immutable 冷读可能滞后于活写者, 报告必须可见。
    """

    def test_legal_terminal_not_counted_as_held(self, tmp_path: Path) -> None:
        import sqlite3

        root = tmp_path / "synthetic-arm-root"
        (root / "arms" / "champion").mkdir(parents=True)
        conn = sqlite3.connect(root / "arms" / "champion" / "capital.sqlite3")
        conn.execute(
            "CREATE TABLE nav_observations ("
            " as_of TEXT, nav_cents INTEGER, capital_version INTEGER,"
            " issued_unit_quanta INTEGER)"
        )
        conn.execute(
            """
            CREATE TABLE positions (
                position_lineage_id TEXT, economic_lot_id TEXT,
                security_id TEXT, state TEXT, settled_quantity_units INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO positions VALUES ('l1','lot1','300001.SZ','OPEN',100)"
        )
        conn.execute(
            "INSERT INTO positions VALUES"
            " ('l2','lot2','600000.SH','LEGAL_TERMINAL',200)"
        )
        conn.execute(
            "INSERT INTO positions VALUES"
            " ('l3','lot3','000001.SZ','EXIT_PENDING',300)"
        )
        conn.execute(
            "INSERT INTO positions VALUES ('l4','lot4','000002.SZ','CLOSED',400)"
        )
        conn.commit()
        conn.close()

        report = _status_json("--trial-root", str(root), "--json")
        arm = report["arms"]["champion"]
        assert arm["status"] == "ok"
        assert arm["open_position_count"] == 2  # OPEN + EXIT_PENDING, 绝非 3
        assert {p["state"] for p in arm["open_positions"]} == {
            "OPEN",
            "EXIT_PENDING",
        }

    def test_zero_byte_decisions_db_is_not_initialized(self, tmp_path: Path) -> None:
        root = tmp_path / "zero-byte-root"
        root.mkdir()
        (root / "decisions.sqlite3").write_bytes(b"")
        report = _status_json("--trial-root", str(root), "--json")
        assert report["decisions"]["status"] == "not_initialized"

    def test_empty_schema_decisions_db_is_not_initialized(
        self, tmp_path: Path
    ) -> None:
        import sqlite3

        root = tmp_path / "empty-schema-root"
        root.mkdir()
        conn = sqlite3.connect(root / "decisions.sqlite3")
        conn.execute("CREATE TABLE unrelated (x)")  # 合法 sqlite, 无决策表
        conn.commit()
        conn.close()
        report = _status_json("--trial-root", str(root), "--json")
        assert report["decisions"]["status"] == "not_initialized"

    def test_wal_sidecar_freshness_disclosed(self, tmp_path: Path) -> None:
        world = _DriverWorld(tmp_path)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        _settle_world(world)

        copy_root = tmp_path / "wal-copy"
        shutil.copytree(world.root, copy_root)
        (copy_root / "decisions.sqlite3-wal").write_bytes(b"x" * 4096)

        report = _status_json("--trial-root", str(copy_root), "--json")
        sidecars = report["sidecars"]
        assert sidecars["decisions.sqlite3"]["wal_bytes"] == 4096
        # 主体事实不受假 wal 影响 (immutable 冷读主文件)
        assert report["decisions"]["status"] == "ok"

        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status_main(["--trial-root", str(copy_root)])
        assert "WAL" in buffer.getvalue() or "wal" in buffer.getvalue()
