"""court 判定面夜度保鲜编排器 (R93 Op1) — NS-5 run_daily_regime_refresh 同款先例.

判定面 (触发器账本『稳定越零』/ gap 罚分证据 / 先验对齐披露) 的机械耦合
终点在 btst_court_build 成功后的 R84 判定刷新钩子, 但 fetch+build 本身只
存在于人工运行 — 数据停更时三类证据静默冻结在最后覆盖日, 操作员只看到
被动披露 (court 覆盖至 X) 而无机制。本编排器把刷新接进夜度链 (launcher
heredoc 调用, 与 flywheel/regime_refresh 步骤同模式):

1. fetch: ``scripts/btst_court_fetch.py`` 默认参数即前向增长契约
   (daily 自 PANEL_START、limit_list 自 WINDOW_A_START; H1 2025 回填已由
   R89 完成), 幂等续传。
2. build: ``--start`` 从生产 manifest 的 ``window.start`` 派生 — 表自身
   是窗口真话 (R89 Op1), 不在本模块二次硬编码; manifest 缺失/损坏/窗口
   缺失 → skip (建立判定面是人为决策, 编排器绝不擅自发明窗口)。

fail-open 纪律: 任何失败只进结构化 status + 打印, 绝不抛 — 夜度链的
生产步骤 (--auto / --daily-action) 永不被研究面刷新阻断。fetch 失败
(含超时) 时跳过 build: 绝不在可能撕裂的原料上重建; 跳过自愈无损 —
同数据重建本就被前进门 (require_advance) skip, 只损失一夜刷新。
判定刷新的账本保护在 build 侧钩子 (R84 数据前进门 + R93 built_at 出身份),
本模块不重复其语义。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable

# 与 scripts/_btst_court_common.py TABLE_DIR 单源 (drift-guard 见测试):
# build 换目录而编排器不知 → 从旧 manifest 派生旧窗口重建错表。
COURT_TABLE_DIR_REL = "data/research/btst_court/event_tables"

# 夜刷结构化 status 的落盘位置 (R115 Op2): stdout 只进 launcher 日志,
# --daily-action 证据新鲜度告警行需要磁盘真话做 fetch/build 失败归因。
COURT_REFRESH_STATUS_REL = "data/reports/court_refresh_status.json"

# 宇宙对齐 canonical summary (R118 Op1): journal vs court 对账的 undated
# 原子落盘 — build 成功 (表已重建) 后单写者刷新, --daily-action 宇宙对齐行
# 唯一消费面。fetch 失败/窗口未建 (build skip) 时 court 表未变, 不重算
# (fresh install 无表只会产生失败噪声; summary 保持上一次日期, 对齐行明示)。
RECONCILE_SCRIPT_REL = "scripts/btst_realized_vs_court.py"
ALIGNMENT_SUMMARY_REL = "data/reports/realized_vs_court_alignment.json"
RECONCILE_TIMEOUT_S = 300

# 胜率/赔率证据链诊断报告 (R133 Op3): build 成功后逐个 fail-open 刷新 —
# 这些报告此前只靠手动运行, 静默陈旧在最后手动日 (项 8『活文档随 court
# 重建刷新』的实现面)。每脚本独立超时独立容错, 一个失败不阻断其余,
# 失败只进 status["diagnostics"], ok 语义不变。
# R135 Op1: stock_feature_attribution (R134 Op1) 提交晚于保鲜链建立曾静默
# 缺席 — 成员全集由 test_diagnostic_scripts_pinned_set 钉死防再漏接。
DIAGNOSTIC_SCRIPTS: tuple[str, ...] = (
    "scripts/winrate_payoff_decomposition.py",
    "scripts/btst_signal_day_cohort.py",
    "scripts/realized_selection_wedge.py",
    "scripts/day_feature_attribution.py",
    "scripts/stock_feature_attribution.py",
    "scripts/zero_hit_day_gate_attribution.py",
    # R152 Op1: 强度分量级解剖 — 成员随诊断面契约扩展 (R133/R135 同门先例),
    # pinned-set 测试同步钉住防再漏接。
    "scripts/strength_component_decomposition.py",
    # R155 Op1: Kelly 先验条件化评估 (R15) — 胜率/赔率预注册触发器工具中
    # 唯一仍靠手动运行的成员 (报告停在最后手动日), 同门接线 (R152/R135 先例);
    # court 数据增长后的 split-half 符号一致性重读由此每夜自动保鲜。
    "scripts/kelly_prior_conditioning_eval.py",
    # R156 Op1: 最后两个手动面入链 (R155 Op2 登记的 frontier 开放项, 同门
    # 接线第 4 次) — selection anatomy (R99 top_1 优势恒等归因/带内日内排名
    # /拥挤度, 强度阈值正交杠杆假设的预注册证据面) 与 exit anatomy (MFE/MAE
    # /时间到峰 + 诚实止损反事实网格, 8 项清单项 5 止损启用判定输入);
    # 宿主实测裸跑 10.9s/16.4s ≪ 600s, bare 可跑/无必需参数。
    "scripts/btst_daily_selection_anatomy.py",
    "scripts/btst_exit_anatomy.py",
    # R166 Op1: regime 邻近度条件化诊断 (owner 胜率/赔率工作线新轴) — 信号日
    # 按距上一阻断日 (crisis|risk_off) 的会话数分桶 (d1/d2_5/d6p), 回答 normal
    # 池聚合 E 是否为 d1 翻转日与 d2+ 稳定日的混合 (Observe 探针: d1 E=-1.43%
    # n=801 vs d2_5 +1.23%, split-half 跨半一致); 同门接线 (R133/R135 先例),
    # pinned-set 测试同步钉住防再漏接。
    "scripts/regime_proximity_conditioning.py",
    # R168 Op1: regime 阻断连跑条件化诊断 (邻近度轴的二维深化) — 距离 × 前导
    # 阻断连跑长度 (单日闪断 d1_blip vs 连续危机 d1_run), 回答 d1 罚分属连跑
    # 危机机制还是任何阻断后首日机制 (Observe 探针: blip +1.77% vs run −5.74%,
    # 配对差 CI [+2.49%,+11.94%] 越零 — 工作线首个决定性对比); 同门接线
    # (R133/R135/R166 先例), pinned-set 测试同步钉住防再漏接。
    "scripts/regime_blocked_run_conditioning.py",
    # R170 Op1: d1_run 决定性对比的规格稳健性审计 (owner 重入规则决策的证据
    # 质量面) — 循环移位精确置换 placebo (穷举零 RNG 时序识别力) / leave-one-
    # day-out 影响集中度 (脆弱性) / 定义替代敏感度 (run≥3 阈值/label 分解/
    # 剂量反应); 两种走向 (稳健→决策级/脆弱→降格) 都推进证据质量, 同门接线
    # (R133/R135/R166/R168 先例), pinned-set 测试同步钉住防再漏接。
    "scripts/regime_run_contrast_robustness.py",
    # R172 Op1: 超额收益 beta/selection 恒等分解 (工作线证据的机制归属面) —
    # 净收益 = 等权全市场 open→open 基准 + 超额 (与 court 执行口径同窗, 顺延
    # 语义一致), 回答 d1_run 罚分与全体池优势多少是市场 beta 多少是 selection;
    # 逐候选窗口重算 gross 逐位自检 (窗口约定漂移 fail-closed); 同门接线
    # (R133/R135/R166/R168/R170 先例), pinned-set 测试同步钉住防再漏接。
    "scripts/regime_excess_return_decomposition.py",
    # R179 Op1: R168 时代条件性的宇宙构成判别 (R178 登记开放项第一轴收口) —
    # 当前表限制到早期表 symbol 全集 (构成匹配视图) 后同轴重跑, 机械判别
    # 『时代差是构成伪影还是行为/幸存者残余』 (Observe 探针: 匹配后罚分
    # +7.09pp CI [+1.96,+11.93] ≈ 全宇宙 +7.51pp — 构成轴初判不解释);
    # 当前侧随 court 重建每夜保鲜 (早期表冻结); 同门接线第 9 次
    # (R133/R135/R166/R168/R170/R172 先例), pinned-set 测试同步钉住防再漏接。
    "scripts/regime_run_universe_match_validation.py",
    # R180 Op1: R168 时代条件性的幸存者敏感度界 (R179 登记开放项第二轴
    # 收口) — 早期缺席退市票 (隐藏行) 份额 phi 网格下复制当前点罚分所需的
    # 隐藏 run-vs-blip 差分/均值 (混合代数) + 机械不可能旗标 (所需均值低于
    # 全早期表最差单行) + 日均值极距锚点反演; 把机制二元从叙事判断转为可
    # 读数判断。当前侧随 court 重建每夜保鲜 (早期表冻结); 同门接线第 10 次
    # (R133/R135/R166/R168/R170/R172/R179 先例), pinned-set 测试同步钉住
    # 防再漏接。
    "scripts/regime_run_survivorship_sensitivity_validation.py",
)
DIAGNOSTIC_TIMEOUT_S = 600

FetchBuildRunner = Callable[[list[str], Path, int], tuple[int, str, str]]


def _default_runner(args: list[str], cwd: Path, timeout_s: int) -> tuple[int, str, str]:
    """venv 内同解释器执行 scripts 子命令 (继承 env: launcher 已注入 .env)。"""
    proc = subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout_s,
    )
    return proc.returncode, (proc.stdout or ""), (proc.stderr or "")


def _manifest_window_start(table_dir: Path) -> str | None:
    """生产 manifest 的 window.start (窗口真话单一来源); 不可得 → None。"""
    try:
        manifest = json.loads((table_dir / "manifest_v1.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    window = manifest.get("window")
    if not isinstance(window, dict):
        return None
    start = window.get("start")
    return start if isinstance(start, str) and start else None


def _tail(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def _run_step(
    runner: FetchBuildRunner, args: list[str], cwd: Path, timeout_s: int
) -> tuple[int | None, str | None]:
    """执行一步; 失败收敛为 (rc|None, error) — 任何异常都不外抛 (R93 Op2:
    夜度无人值守步骤的失败必须可从 status 归因, stderr 尾部并入 error)。"""
    try:
        rc, out, err = runner(args, cwd, timeout_s)
    except subprocess.TimeoutExpired as exc:
        return None, f"timeout after {timeout_s}s: {exc}"
    except subprocess.SubprocessError as exc:  # 非超时变体 — fail-open 全族
        return None, f"subprocess failure: {exc}"
    except OSError as exc:
        return None, f"spawn failed: {exc}"
    if rc != 0:
        detail = _tail(err) or _tail(out)
        return rc, f"exit rc={rc}" + (f": {detail}" if detail else "")
    return rc, None


def _persist_status(root: Path, status: dict[str, object]) -> None:
    """结构化 status 原子落盘 (R115 Op2): tempfile + fsync + os.replace。

    落盘失败 advisory 不抛 (夜刷 fail-open 家族纪律 — 判定面刷新本身
    绝不被诊断面写坏阻断); 缺席时新鲜度告警行只少归因子句, 不假装。
    """
    path = root / COURT_REFRESH_STATUS_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".court_refresh_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(status, fh, ensure_ascii=False, indent=1)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        print(f"WARNING: court 刷新状态落盘失败 (advisory, 不阻断): {exc}")


def run_court_nightly_refresh(
    repo_root: Path | None = None,
    *,
    fetch_timeout_s: int = 900,
    build_timeout_s: int = 1800,
    _runner: FetchBuildRunner | None = None,
) -> dict[str, object]:
    """fetch → build 一夜保鲜; 返回结构化 status, 绝不抛。

    status 形态::

        {"date": "20260902",
         "fetch": {"rc": 0, "error": None} | {"rc": None, "error": "..."},
         "build": {"rc": 0, "window_start": "20250102", "error": None}
                  | {"skipped": "<reason>"},
         "reconcile": {"rc": 0, "error": None},   # 仅 build 成功后存在 (R118)
         "diagnostics": {script: {"rc": 0, "error": None}, …},
                                                   # 仅 build 成功后存在 (R133 Op3)
         "ok": bool}

    ``ok`` = fetch 成功且 build 成功或合法 skip (判定面未建立是稳态, 不是错误)。
    """
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    runner: FetchBuildRunner = _runner if _runner is not None else _default_runner
    status: dict[str, object] = {"date": date.today().strftime("%Y%m%d")}

    fetch_rc, fetch_err = _run_step(
        runner, ["scripts/btst_court_fetch.py"], root, fetch_timeout_s
    )
    status["fetch"] = {"rc": fetch_rc, "error": fetch_err}

    if fetch_rc != 0 or fetch_err is not None:
        # 绝不在可能撕裂的原料上重建 (跳过自愈无损: 同数据重建本被前进门 skip)
        status["build"] = {"skipped": "fetch_failed"}
        status["ok"] = False
    else:
        window_start = _manifest_window_start(root / COURT_TABLE_DIR_REL)
        if window_start is None:
            status["build"] = {
                "skipped": "court_manifest_missing_or_window_missing"
            }
            status["ok"] = True
        else:
            build_rc, build_err = _run_step(
                runner,
                ["scripts/btst_court_build.py", "--start", window_start],
                root,
                build_timeout_s,
            )
            status["build"] = {
                "rc": build_rc,
                "window_start": window_start,
                "error": build_err,
            }
            status["ok"] = build_rc == 0 and build_err is None

    # 宇宙对齐刷新 (R118 Op1): 只在 build 成功后重算 — 对账消费的是刚重建的
    # court 表与最新 journal; build skip/失败时表未变, summary 保持原日期由
    # 对齐行明示。诊断面 fail-open: 失败只进 status["reconcile"], ok 语义不变。
    build_status = status.get("build")
    if isinstance(build_status, dict) and build_status.get("rc") == 0:
        reconcile_rc, reconcile_err = _run_step(
            runner,
            [RECONCILE_SCRIPT_REL, "--summary-json", ALIGNMENT_SUMMARY_REL],
            root,
            RECONCILE_TIMEOUT_S,
        )
        status["reconcile"] = {"rc": reconcile_rc, "error": reconcile_err}

        # 证据链诊断报告保鲜 (R133 Op3): 与 reconcile 同门 (只在表重建后),
        # 逐脚本独立 fail-open — 一个失败不阻断其余, ok 语义不变。
        diagnostics: dict[str, object] = {}
        for script_rel in DIAGNOSTIC_SCRIPTS:
            diag_rc, diag_err = _run_step(
                runner, [script_rel], root, DIAGNOSTIC_TIMEOUT_S
            )
            diagnostics[script_rel] = {"rc": diag_rc, "error": diag_err}
        status["diagnostics"] = diagnostics

    _persist_status(root, status)
    print("court_nightly_refresh:", json.dumps(status, ensure_ascii=False))
    return status
