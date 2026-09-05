"""scripts.threshold_trigger_k_packet — owner K 决策包 CLI (R129 Op2)。

钉死的正确性面:
- preview 默认零写入 (A2: 运行前后目录逐条目相等);
- 判定逻辑零新增 — stability/qualification/disclosure 全部
  threshold_trigger + cohort_trigger 单一实现复用, 工具只拼装呈现;
- --write 是 owner 亲自执行的预注册动作: 落盘规范形状草案, 已存在拒绝
  覆写 (改写注册 = 新 hash = 新观测起算窗, 静默替换是回溯向量);
- 路径全可注入 — 验证 slot 自足 (R10 教训: 依赖 gitignored 资产的
  命令不能作 slot verification)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.threshold_trigger_k_packet import build_packet, main


def _strength_ledger(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "threshold_trigger_ledger.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _srow(date: str, *, c1=True, c2=False, armed=False) -> dict:
    return {
        "date": date,
        "anchor": "production_aligned/t10",
        "min_n": 30,
        "condition_1": {"lit": c1, "judged": True, "n": 340, "stat": 0.0007},
        "condition_2": {"lit": c2, "judged": True, "n": 341, "stat": 0.0014},
        "conjunction_armed": armed,
        "court": {"window_end": date, "rows": 1627},
    }


def _crow(date: str, *, armed=True) -> dict:
    return {
        "date": date,
        "anchor": "production_aligned/t10/cohort_size",
        "min_n": 30,
        "strong_bucket": {"lit": True, "judged": True, "n": 864, "stat": 0.001},
        "mid_buckets": {"lit": True, "judged": True, "n": 293, "stat": -0.001},
        "conjunction_armed": armed,
        "court": {"window_end": date, "rows": 1627},
    }


def _paths(tmp_path: Path):
    return {
        "strength_ledger": tmp_path / "threshold_trigger_ledger.jsonl",
        "strength_k_registration": tmp_path / "threshold_trigger_k.json",
        "strength_k_observation_log": tmp_path / "threshold_trigger_k_obs.jsonl",
        "cohort_ledger": tmp_path / "signal_day_cohort_trigger_ledger.jsonl",
        "cohort_k_registration": tmp_path / "cohort_trigger_k.json",
        "cohort_k_observation_log": tmp_path / "cohort_trigger_k_obs.jsonl",
    }


def _snapshot(root: Path) -> dict:
    return {
        p.name: p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class TestPreviewZeroWrite:
    def test_preview_touches_nothing(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        _strength_ledger(tmp_path, [
            _srow("20260903"), _srow("20260904"), _srow("20260905"),
        ])
        before = _snapshot(tmp_path)
        rc = main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(paths["cohort_ledger"]),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            "--k070", "3",
        ])
        assert rc == 0
        assert _snapshot(tmp_path) == before

    def test_registered_family_without_file_reports_unregistered(
        self, tmp_path, capsys
    ):
        paths = _paths(tmp_path)
        _strength_ledger(tmp_path, [_srow("20260905")])
        rc = main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing_cohort.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "强度族" in out
        assert "未预注册" in out
        # 缺日层账本 → 该族披露无账本而非崩溃
        assert "日层族" in out


class TestPacketContent:
    def test_strength_stability_numbers_from_single_implementation(
        self, tmp_path, capsys
    ):
        paths = _paths(tmp_path)
        _strength_ledger(tmp_path, [
            _srow("20260902", armed=True),
            _srow("20260903", armed=True),
            _srow("20260904", armed=True),
        ])
        rc = main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "合取连亮 3" in out
        assert "历史最多合取连亮 3" in out
        assert "账本 3 条" in out

    def test_candidate_k_projection_math(self, tmp_path, capsys):
        """候选 K 推演 = 假想注册 (registered_date=--registered-date) 的资格
        判定 — 3 连亮武装 + 注册日早于亮起点 + K=3 → 达标。"""
        paths = _paths(tmp_path)
        _strength_ledger(tmp_path, [
            _srow("20260902", armed=True),
            _srow("20260903", armed=True),
            _srow("20260904", armed=True),
        ])
        main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            "--k070", "3",
            "--registered-date", "20260901",
        ])
        out = capsys.readouterr().out
        assert "资格连亮 3/3" in out
        assert "达标" in out

    def test_candidate_k_after_first_lit_does_not_backcount(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        _strength_ledger(tmp_path, [
            _srow("20260902", armed=True),
            _srow("20260903", armed=True),
            _srow("20260904", armed=True),
        ])
        main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            "--k070", "3",
            "--registered-date", "20260904",
        ])
        out = capsys.readouterr().out
        assert "资格连亮 1/3" in out

    def test_draft_json_shape_both_families(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        _strength_ledger(tmp_path, [_srow("20260905")])
        main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            "--k070", "3",
            "--cohort-k", "2",
            "--registered-date", "20260906",
        ])
        out = capsys.readouterr().out
        assert '"anchor": "production_aligned/t10"' in out
        assert '"k_070": 3' in out
        assert '"anchor": "production_aligned/t10/cohort_size"' in out
        assert '"k": 2' in out
        assert '"registered_date": "20260906"' in out

    def test_cohort_family_projection(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        cohort_ledger = tmp_path / "signal_day_cohort_trigger_ledger.jsonl"
        cohort_ledger.write_text(
            "\n".join(
                json.dumps(r, ensure_ascii=False)
                for r in [_crow("20260904"), _crow("20260905"), _crow("20260906", armed=False)]
            )
            + "\n",
            encoding="utf-8",
        )
        main([
            "--strength-ledger", str(tmp_path / "missing.jsonl"),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(cohort_ledger),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            "--cohort-k", "2",
            "--registered-date", "20260901",
        ])
        out = capsys.readouterr().out
        # 最新行未武装断链 → 资格连亮 0
        assert "日层族" in out
        assert "资格连亮 0/2" in out

    def test_malformed_existing_registration_disclosed(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        _strength_ledger(tmp_path, [_srow("20260905")])
        paths["strength_k_registration"].write_text("{corrupted", encoding="utf-8")
        main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
        ])
        out = capsys.readouterr().out
        assert "损坏" in out

    def test_registered_existing_reports_effective_window(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        ledger = _strength_ledger(tmp_path, [
            _srow("20260904", armed=True),
            _srow("20260905", armed=True),
        ])
        reg = {
            "anchor": "production_aligned/t10",
            "registered_date": "20260901",
            "k_070": 2,
        }
        paths["strength_k_registration"].write_text(
            json.dumps(reg, ensure_ascii=False), encoding="utf-8"
        )
        main([
            "--strength-ledger", str(ledger),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
        ])
        out = capsys.readouterr().out
        assert "已预注册" in out
        assert "K=2" in out
        assert "资格连亮 2/2" in out


class TestWriteFace:
    def _argv(self, tmp_path, paths, *extra):
        _strength_ledger(tmp_path, [_srow("20260905")])
        return [
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            "--k070", "3",
            "--registered-date", "20260906",
            *extra,
        ]

    def test_write_creates_registration_readable_by_loader(
        self, tmp_path, capsys
    ):
        from src.screening.offensive.threshold_trigger import load_k_registration

        paths = _paths(tmp_path)
        rc = main(self._argv(tmp_path, paths, "--write"))
        assert rc == 0
        state, reg = load_k_registration(paths["strength_k_registration"])
        assert state == "registered"
        # loader 规范形状: k_060 缺失归一为 None (强度族既有契约)
        assert reg == {
            "anchor": "production_aligned/t10",
            "registered_date": "20260906",
            "k_070": 3,
            "k_060": None,
        }

    def test_write_refuses_overwrite_existing(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        paths["strength_k_registration"].write_text(
            json.dumps({"anchor": "production_aligned/t10", "registered_date": "20260901", "k_070": 9}),
            encoding="utf-8",
        )
        rc = main(self._argv(tmp_path, paths, "--write"))
        assert rc != 0
        out = capsys.readouterr().out
        assert "拒绝覆写" in out
        # 既有文件字节未动
        assert json.loads(paths["strength_k_registration"].read_text(encoding="utf-8"))["k_070"] == 9

    def test_write_without_candidate_k_fails_closed(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        rc = main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            "--write",
        ])
        assert rc != 0


class TestBuildPacketPure:
    def test_build_packet_returns_structured_dict(self, tmp_path):
        paths = _paths(tmp_path)
        ledger = _strength_ledger(tmp_path, [
            _srow("20260904", armed=True),
            _srow("20260905", armed=True),
        ])
        from src.screening.offensive.threshold_trigger import (
            load_trigger_ledger,
        )

        packet = build_packet(
            family="strength",
            records=load_trigger_ledger(ledger),
            ledger_path=ledger,
            k_registration_path=paths["strength_k_registration"],
            k_observation_log_path=paths["strength_k_observation_log"],
            candidates={"k_070": 2},
            registered_date="20260901",
        )
        assert packet["stability"]["records"] == 2
        assert packet["registration"]["state"] == "unregistered"
        draft = json.loads(packet["draft"]) if isinstance(packet["draft"], str) else packet["draft"]
        assert draft["k_070"] == 2
        assert draft["registered_date"] == "20260901"
        assert packet["candidate_070"]["qualified"] is True


class TestCandidateValidation:
    """F3 (R129 Op3): 候选形状前置校验 — preview/write 双面 fail-closed。"""

    def _argv(self, tmp_path, paths, *extra):
        return [
            "--strength-ledger", str(tmp_path / "missing.jsonl"),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing_c.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
            *extra,
        ]

    def test_negative_k_preview_fails_closed_not_crash(self, tmp_path, capsys):
        """负数 K 此前在假想推演处触发 trigger_qualification 形状复验
        ValueError 裸逃逸 (preview 崩溃); 现在前置校验 exit 2。"""
        paths = _paths(tmp_path)
        rc = main(self._argv(tmp_path, paths, "--k070", "-3"))
        assert rc == 2
        assert "必须 >=1" in capsys.readouterr().out

    def test_zero_k_rejected(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        rc = main(self._argv(tmp_path, paths, "--cohort-k", "0"))
        assert rc == 2

    def test_malformed_registered_date_rejected(self, tmp_path, capsys):
        paths = _paths(tmp_path)
        rc = main(self._argv(tmp_path, paths, "--k070", "3", "--registered-date", "2026-9-6"))
        assert rc == 2
        assert "YYYYMMDD" in capsys.readouterr().out

    def test_k060_only_write_rejected(self, tmp_path, capsys):
        """仅 k_060 的强度注册会落成 loader malformed 文件 — 拒绝。"""
        paths = _paths(tmp_path)
        rc = main(self._argv(
            tmp_path, paths, "--k060", "3", "--registered-date", "20260906", "--write"
        ))
        assert rc == 2
        assert "k_070" in capsys.readouterr().out
        assert not paths["strength_k_registration"].exists()

    def test_k060_without_k070_preview_also_rejected(self, tmp_path, capsys):
        """仅 k_060 即使 preview 也拒 — 推演无法构成合法假想注册。"""
        paths = _paths(tmp_path)
        rc = main(self._argv(tmp_path, paths, "--k060", "3"))
        assert rc == 2


class TestFoldDisclosure:
    def test_fmt_stability_discloses_folded_duplicates(self, tmp_path, capsys):
        """R130 Op2: 折叠>0 → 决策包披露; 干净账本零新增。"""
        paths = _paths(tmp_path)
        rows = [
            _srow("20260904", armed=True),
            _srow("20260905", armed=True),
        ]
        for r in rows:
            r["court"]["content_digest"] = "sha256:" + "e3" * 32
        _strength_ledger(tmp_path, rows)
        rc = main([
            "--strength-ledger", str(paths["strength_ledger"]),
            "--strength-k-registration", str(paths["strength_k_registration"]),
            "--strength-k-observation-log", str(paths["strength_k_observation_log"]),
            "--cohort-ledger", str(tmp_path / "missing.jsonl"),
            "--cohort-k-registration", str(paths["cohort_k_registration"]),
            "--cohort-k-observation-log", str(paths["cohort_k_observation_log"]),
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "折叠同数据重复观测 1 条" in out
        assert "合取连亮 1" in out  # 同状态重复观测不膨胀连亮
