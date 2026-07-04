"""R88 corrupt-report CRASH vector (BTST analysis artifacts): ``_write_analysis_artifacts``
must write the ``.json`` artifact atomically so a crash mid-write leaves any prior
artifact intact, not truncated. Reuses c294's atomic ``_write_json`` helper from
``btst_reporting_utils`` (already imported in btst_reporting.py at line 195).
"""

from __future__ import annotations

import json
from pathlib import Path


def test_write_analysis_artifacts_json_write_is_atomic(tmp_path: Path, monkeypatch) -> None:
    """The .json artifact write must survive a mid-write crash (prior intact or new-complete,
    never truncated/corrupt). Non-atomic write_text truncates on open(mode='w'); atomic
    _write_json (tempfile + os.replace) never truncates the final path until commit."""
    from src.paper_trading.btst_reporting import _write_analysis_artifacts

    output_json = tmp_path / "analysis.json"
    output_json.write_text(json.dumps({"prior": True, "keep": "alive"}), encoding="utf-8")

    # Crash ONLY .json write_text (scoped by suffix); .md writes proceed.
    _original_write_text = Path.write_text

    def crashing_write_text(self, data, *args, **kwargs):  # noqa: ANN001
        if self.suffix == ".json":
            open(self, "w").close()  # write_text opens mode='w' → truncates
            raise OSError("simulated mid-write crash on json artifact")
        return _original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", crashing_write_text)

    try:
        _write_analysis_artifacts(
            payload={"new": "analysis", "v": 2},
            render_markdown=lambda payload: "# analysis md",
            resolved_output_dir=tmp_path,
            stem="analysis",
        )
    except OSError:
        pass  # acceptable: the write reported failure; the guard is about file state

    raw = output_json.read_text(encoding="utf-8")
    assert raw.strip(), "prior analysis.json must not be truncated-empty after a crashed write — " "non-atomic write_text truncates on open (R88 corrupt-report CRASH vector root cause)"
    parsed = json.loads(raw)  # must parse cleanly — no half-written corrupt file
    assert parsed.get("keep") == "alive" or parsed.get("new") == "analysis", "final artifact must hold either the prior or the new complete payload — never a corrupt half-write"
