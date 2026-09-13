"""trial_capacity_fit_diagnostic — Trial 容量适配诊断 (R213 Op1, 纯披露).

Observe 实锤 (2026-09-14): 官方前向 Trial (trial-btst-regime-r1) 的 2% canary
容量包络与 BTST 涨停突破候选的价格分布结构性错配 —
- 封存 challenger policy capital.portfolio_gross_cap = 0.02, genesis NAV
  ¥100,000 → 组合上限 ≈ ¥2,000 (`_constraints_by_lineage`: int(NAV×fraction));
- 官方 SizingConfig per_ticker = ¥2,000 (scripts/v3_trial_session.py);
- 100 股整手下, 单手成交要求股价 ≤ 组合上限/100 ≈ ¥20.00;
- court 生产对齐候选 signal_close 中位 ¥21.87 → 仅 ~47% 候选单手可塞入;
- trial 实况: 11 已决策会话 2 RUN vs 3 CAPACITY_EXHAUSTED (信号日 60%
  无法成交), 官方证据引擎逐会话被容量线烧掉, 且成交子集系统性偏向低价股。

本工具把「逐候选容量 fit 判定」用 kernel `size_portfolio` 单一实现逐点重演
(绝不 fork 容量语义), 聚合出 fit 率 / crisis-normal 分拆 / fitted vs
not-fitted t10 净期望 / genesis 规模 what-if 表 — 给 owner 的 genesis units
决策 (落账后永久经济事实, owner 显式决策) 提供数字面。

纯诊断 (宪法 #2: 只披露不判定); 不改变 trial/policy/sizing 任何生产行为;
调整 genesis units / policy caps = 新证据世代 owner 决策。

诚实披露 (上界性质, render_md 复述):
- 价格代理 = court `signal_close` (T0 收盘)。trial 实际 sizing 价 =
  producer `entry_price` (同源于信号快照价, R210 S1 语义), 极端情形可异;
- fit 率是**上界**: 探针候选 unscaled_target 取包络上界 (生产 kelly 权重
  若 < cap fraction 则目标更低更难 fit), 且 industry/day 槽位按单候选空槽
  计 (同行业多候选当日会先耗尽), 组合余量按 existing=0 计 (持仓在库时
  余量更低);
- court 生产对齐宇宙是反事实候选宇宙 (陷阱 19: 证据宇宙 = court 全候选),
  非 trial producer 的实际 SELECTED 集; 实况对照属宿主冒烟证据, 不入本工具。

实现单一事实源纪律: 复用 winrate 工具 (production_aligned/net_returns/
win_loss_stats/MIN_CELL_N) 与 kernel sizing (size_portfolio/SizingConfig/
RawCandidate 单一实现); 新增的只有包络算术 (TrialEnvelope + fits_trial 单
候选重演) 与判读装配。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.regime_proximity_conditioning import (
    BLOCKED_REGIMES,
    COURT_TABLE_DEFAULT,
    REPORT_DIR_DEFAULT,
)
from scripts.winrate_payoff_decomposition import (
    MIN_CELL_N,
    net_returns,
    production_aligned,
    win_loss_stats,
)
from src.screening.offensive.v3.kernel.admission import BTST_FAMILY
from src.screening.offensive.v3.kernel.models import RawCandidate
from src.screening.offensive.v3.kernel.sizing import (
    SizingConfig,
    size_portfolio,
)

REPORT_STEM = "trial_capacity_fit_diagnostic"

# 官方 Trial 容量包络默认值。前四者 = scripts/v3_trial_session.py
# `_build_stack` 的 SizingConfig 字面量 (漂移有测试钉死, 源文件改动即红);
# portfolio_cap_fraction = 封存 challenger policy (policy-v2) 的
# capital.portfolio_gross_cap; nav 默认 = genesis ¥100,000 (live NAV 用
# --nav-cents 覆盖; champion 2026-09-11 为 9,972,797 cents)。
DEFAULT_PER_TICKER_GROSS_CAP_CENTS = 200_000
DEFAULT_PER_INDUSTRY_GROSS_CAP_CENTS = 300_000
DEFAULT_PER_DAY_GROSS_CAP_CENTS = 500_000
DEFAULT_WORST_CASE_FEE_PPM = 3_000
DEFAULT_PORTFOLIO_CAP_FRACTION = 0.02
DEFAULT_LOT_UNITS = 100
DEFAULT_NAV_CENTS = 10_000_000

DEFAULT_SCALES: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 20.0)

PROBE_LINEAGE_ID = "eline-fit-probe"
PROBE_PROGRAM_ID = "prog-fit-probe"
PROBE_STAGE_ID = "stage-fit-probe"
PROBE_FINGERPRINT = "0" * 64


class TrialCapacityFitError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class TrialEnvelope:
    """官方 Trial 容量包络 (整数 cents; 与 kernel sizing 同一口径)."""

    nav_cents: int
    portfolio_cap_fraction: float
    per_ticker_gross_cap_cents: int
    per_industry_gross_cap_cents: int
    per_day_gross_cap_cents: int
    worst_case_fee_ppm: int
    lot_units: int

    def __post_init__(self) -> None:
        if self.nav_cents <= 0:
            raise TrialCapacityFitError(
                "invalid_envelope", "nav_cents must be positive"
            )
        if not 0.0 < self.portfolio_cap_fraction <= 1.0:
            raise TrialCapacityFitError(
                "invalid_envelope", "portfolio_cap_fraction must be in (0, 1]"
            )
        if min(
            self.per_ticker_gross_cap_cents,
            self.per_industry_gross_cap_cents,
            self.per_day_gross_cap_cents,
        ) < 0 or self.worst_case_fee_ppm < 0 or self.lot_units <= 0:
            raise TrialCapacityFitError(
                "invalid_envelope", "caps/fee/lot must be non-negative"
            )

    @property
    def portfolio_cap_cents(self) -> int:
        # 镜像 kernel `_constraints_by_lineage`: int(NAV × policy fraction)
        return int(self.nav_cents * self.portfolio_cap_fraction)

    def scaled(self, scale: float) -> "TrialEnvelope":
        """genesis 规模 what-if: NAV 等比放大, 其余 caps 同构 (fraction 不变)."""
        if not scale > 0.0:
            raise TrialCapacityFitError(
                "invalid_scale", "scale must be positive"
            )
        return TrialEnvelope(
            nav_cents=int(self.nav_cents * scale),
            portfolio_cap_fraction=self.portfolio_cap_fraction,
            per_ticker_gross_cap_cents=int(
                self.per_ticker_gross_cap_cents * scale
            ),
            per_industry_gross_cap_cents=int(
                self.per_industry_gross_cap_cents * scale
            ),
            per_day_gross_cap_cents=int(self.per_day_gross_cap_cents * scale),
            worst_case_fee_ppm=self.worst_case_fee_ppm,
            lot_units=self.lot_units,
        )

    def _sizing_config(self) -> SizingConfig:
        return SizingConfig(
            per_ticker_gross_cap_cents=self.per_ticker_gross_cap_cents,
            per_industry_gross_cap_cents=self.per_industry_gross_cap_cents,
            per_day_gross_cap_cents=self.per_day_gross_cap_cents,
            portfolio_gross_cap_cents=self.portfolio_cap_cents,
            worst_case_fee_ppm=self.worst_case_fee_ppm,
            min_lot_units=self.lot_units,
        )


def _probe_candidate(candidate_id: str, unscaled_target: int) -> RawCandidate:
    return RawCandidate(
        candidate_id=candidate_id,
        producer_namespace="btst",
        family_id=BTST_FAMILY,
        economic_lineage_id=PROBE_LINEAGE_ID,
        research_program_id=PROBE_PROGRAM_ID,
        stage_id=PROBE_STAGE_ID,
        security_id="PROBE.SH",
        direction="LONG",
        unscaled_target_gross_cents=unscaled_target,
        behavior_fingerprint=PROBE_FINGERPRINT,
        execution_version="fit-probe",
        cost_version="fit-probe",
        evidence_ids=(),
    )


def fits_trial(
    price_cny: float, envelope: TrialEnvelope
) -> tuple[bool, str | None]:
    """单候选容量重演: 该价格的一手该票能否进 ENTRY_PLANNED。

    单一实现: 直接调用 kernel `size_portfolio` (生产 sizing 语义本体),
    探针候选 unscaled_target 取组合包络上界 (上界性质见模块 docstring)。
    price_cny 必须 > 0 且能精确表示为 0.01 tick (调用方先过滤畸形价)。
    """
    if not price_cny > 0:
        raise TrialCapacityFitError(
            "invalid_probe_price", f"price must be positive, got {price_cny!r}"
        )
    cap = envelope.portfolio_cap_cents
    candidate_id = f"fit-probe:{price_cny:.2f}"
    sized = size_portfolio(
        ranked_candidates=(
            _probe_candidate(candidate_id, cap),
        ),
        adjusted_target_gross_by_lineage={PROBE_LINEAGE_ID: cap},
        price_micros_by_candidate={candidate_id: round(price_cny * 1_000_000)},
        industry_by_candidate={candidate_id: "fit-probe"},
        available_cash_cents=envelope.nav_cents,
        config=envelope._sizing_config(),
        adjusted_portfolio_gross_cap_cents=cap,
        existing_portfolio_gross_cents=0,
    )
    line = sized[0]
    if line.status == "ENTRY_PLANNED":
        return True, None
    reason = line.block_reason
    return False, str(getattr(reason, "value", reason))


def candidate_rows(u: "pd.DataFrame", envelope: TrialEnvelope) -> "pd.DataFrame":
    """生产对齐宇宙 → 逐候选 fit 判定行 (畸形价排除并计数)."""
    required = ("symbol", "signal_date", "regime", "signal_close", "gross_ret_t10")
    missing = [c for c in required if c not in u.columns]
    if missing:
        raise TrialCapacityFitError(
            "missing_columns", f"event table missing columns: {missing}"
        )
    rows = []
    price_invalid = 0
    for row in u.itertuples(index=False):
        try:
            price = float(row.signal_close)
        except (TypeError, ValueError):
            price = float("nan")
        if not price == price or price <= 0:  # NaN 或非正价 → 排除
            price_invalid += 1
            continue
        fit, reason = fits_trial(price, envelope)
        rows.append(
            {
                "symbol": row.symbol,
                # 保留原始 dtype (event 表 signal_date 是 int64): merge 键
                # 与源宇宙对齐; win_loss_stats 消费前再 str()
                "signal_date": row.signal_date,
                "regime": str(row.regime),
                "price_cny": price,
                "fit": fit,
                "block_reason": reason,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        raise TrialCapacityFitError(
            "empty_universe", "no candidate rows with a usable signal_close"
        )
    out.attrs["price_invalid_excluded"] = price_invalid
    return out


def _net_t10(u: "pd.DataFrame") -> list[float | None]:
    net = net_returns([float(v) for v in u["gross_ret_t10"].tolist()])
    return [r if (r is not None and math.isfinite(r)) else None for r in net]


def _finite_float(value: object) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def analyze(
    u: "pd.DataFrame",
    envelope: TrialEnvelope,
    scales: tuple[float, ...] = DEFAULT_SCALES,
) -> dict[str, object]:
    """聚合 fit 率 / regime 分拆 / 子集期望 / what-if (纯函数)."""
    rows = candidate_rows(u, envelope)
    price_invalid = int(rows.attrs.get("price_invalid_excluded", 0))
    days = rows.groupby("signal_date")
    day_fit = days["fit"].any()
    prices = sorted(rows["price_cny"].tolist())

    def quantile(q: float) -> float:
        idx = min(int(q * (len(prices) - 1)), len(prices) - 1)
        return round(float(prices[idx]), 2)

    def _subset_stats(sub: "pd.DataFrame") -> dict[str, object]:
        merged = sub.merge(
            u[["symbol", "signal_date", "gross_ret_t10"]],
            on=["symbol", "signal_date"],
            how="left",
        )
        net = _net_t10(merged)
        pairs = [
            (str(d), r)
            for d, r in zip(merged["signal_date"], net)
            if r is not None
        ]
        return win_loss_stats(
            [r for _, r in pairs], [d for d, _ in pairs]
        )

    fitted = rows[rows["fit"]]
    not_fitted = rows[~rows["fit"]]
    regime_split: dict[str, object] = {}
    is_blocked = rows["regime"].astype(str).isin(BLOCKED_REGIMES)
    for label, mask in (
        ("blocked", is_blocked),
        ("normal", ~is_blocked),
    ):
        sub = rows[mask]
        sub_days = sub.groupby("signal_date")["fit"].any()
        regime_split[label] = {
            "n_candidates": int(len(sub)),
            "n_fit": int(sub["fit"].sum()),
            "candidate_fit_rate": (
                round(float(sub["fit"].mean()), 4) if len(sub) else None
            ),
            "n_days": int(len(sub_days)),
            "n_days_fit": int(sub_days.sum()) if len(sub_days) else 0,
            "day_fit_rate": (
                round(float(sub_days.mean()), 4) if len(sub_days) else None
            ),
        }

    what_if: list[dict[str, object]] = []
    for scale in scales:
        scaled = envelope.scaled(scale)
        scaled_rows = candidate_rows(u, scaled)
        scaled_days = scaled_rows.groupby("signal_date")["fit"].any()
        what_if.append(
            {
                "scale": scale,
                "nav_cents": scaled.nav_cents,
                "portfolio_cap_cents": scaled.portfolio_cap_cents,
                "single_lot_max_price_cny": round(
                    scaled.portfolio_cap_cents / scaled.lot_units / 100.0, 2
                ),
                "candidate_fit_rate": round(
                    float(scaled_rows["fit"].mean()), 4
                ),
                "day_fit_rate": round(float(scaled_days.mean()), 4),
            }
        )

    threshold_cny = envelope.portfolio_cap_cents / envelope.lot_units / 100.0
    return {
        "envelope": {
            "nav_cents": envelope.nav_cents,
            "portfolio_cap_fraction": envelope.portfolio_cap_fraction,
            "portfolio_cap_cents": envelope.portfolio_cap_cents,
            "per_ticker_gross_cap_cents": envelope.per_ticker_gross_cap_cents,
            "per_day_gross_cap_cents": envelope.per_day_gross_cap_cents,
            "worst_case_fee_ppm": envelope.worst_case_fee_ppm,
            "lot_units": envelope.lot_units,
            "single_lot_max_price_cny": round(
                threshold_cny, 2
            ),
        },
        "n_candidates": int(len(rows)),
        "n_price_invalid_excluded": price_invalid,
        "n_days": int(day_fit.size),
        "price_quantiles_cny": {
            "p10": quantile(0.10),
            "p25": quantile(0.25),
            "p50": quantile(0.50),
            "p75": quantile(0.75),
            "p90": quantile(0.90),
        },
        "candidate_fit_rate": round(float(rows["fit"].mean()), 4),
        "day_fit_rate": round(float(day_fit.mean()), 4),
        "regime_split": regime_split,
        "fitted_stats": _subset_stats(fitted),
        "not_fitted_stats": _subset_stats(not_fitted),
        "fitted_median_price_cny": (
            round(float(fitted["price_cny"].median()), 2) if len(fitted) else None
        ),
        "not_fitted_median_price_cny": (
            round(float(not_fitted["price_cny"].median()), 2)
            if len(not_fitted)
            else None
        ),
        "what_if": what_if,
        "min_cell_n": MIN_CELL_N,
    }


def render_md(payload: dict[str, object]) -> str:
    """payload → markdown (上界性质与只披露纪律显式成文)."""
    env = payload["envelope"]
    lines = [
        f"# trial 容量适配诊断 ({date.today().isoformat()})",
        "",
        "纯诊断 (宪法 #2: 只披露不判定)。官方 Trial 的 2% canary 容量包络与",
        "BTST 候选价格分布的适配度: 逐候选以 kernel size_portfolio 单一实现",
        "重演容量判定 (绝不 fork 容量语义)。genesis units / policy caps 调整",
        "= 落账后永久经济事实或新证据世代, 均属 owner 决策; 本报告不构成授权。",
        "",
        "## 包络与总体",
        "",
        f"- NAV {env['nav_cents']} cents · 组合上限 {env['portfolio_cap_cents']} cents"
        f" (fraction {env['portfolio_cap_fraction']}) · per_ticker"
        f" {env['per_ticker_gross_cap_cents']} cents · 整手 {env['lot_units']} 股",
        f"- 单手可成交价上界 ≈ ¥{env['single_lot_max_price_cny']}",
        f"- 候选 n={payload['n_candidates']} (畸形价排除"
        f" {payload['n_price_invalid_excluded']}) · 信号日 n={payload['n_days']}",
        f"- 候选 fit 率 {payload['candidate_fit_rate']} · 日 fit 率"
        f" {payload['day_fit_rate']}",
        f"- 价格分位 (CNY): {payload['price_quantiles_cny']}",
        "",
        "## regime 分拆 (日 fit 率)",
        "",
    ]
    for label in ("blocked", "normal"):
        s = payload["regime_split"][label]  # type: ignore[index]
        lines.append(
            f"- {label}: 候选 {s['n_fit']}/{s['n_candidates']} fit"
            f" ({s['candidate_fit_rate']}) · 日 {s['n_days_fit']}/{s['n_days']}"
            f" ({s['day_fit_rate']})"
        )
    blocked_n = payload["regime_split"]["blocked"]["n_candidates"]  # type: ignore[index]
    if blocked_n == 0:
        lines.append(
            "  (blocked n=0 非巧合: production_aligned 宇宙是 post-regime-gate"
            " 的反事实宇宙, crisis 候选已被 gate 排除 — regime 分拆在此宇宙上"
            " 结构性退化, 如实呈现而非补造)"
        )
    lines.append(
        "- 解读: 日 fit 率回答『court 宇宙里是否还有可成交候选』; trial 的"
        " SELECTED 集通常远小于 court 宇宙, 其信号日无法成交概率应对照"
        "**候选级** fit 率解读"
    )
    for name in ("fitted_stats", "not_fitted_stats"):
        s = payload[name]  # type: ignore[index]
        ci = s.get("cluster_ci_low_90")
        note = (
            "n<30 只披露 (CI 缺失即样本不足)"
            if ci is None
            else f"CI90 下界 {round(float(ci), 6)}"
        )
        lines.append(
            f"- {name}: n={s['n']} 胜率={s['winrate']} E={s['expectancy']}"
            f" ({note})"
        )
    fmt = lambda v: "—" if v is None else f"¥{v}"  # noqa: E731
    lines += [
        f"- fitted 中位价 {fmt(payload['fitted_median_price_cny'])} vs"
        f" not-fitted 中位价 {fmt(payload['not_fitted_median_price_cny'])}"
        " — 成交子集偏向",
        "  低价股是容量线的机械结果 (选择轴披露, 与策略强度无关)",
        "",
        "## genesis 规模 what-if (纯反事实; 调整 = owner 决策)",
        "",
        "| scale | NAV (cents) | 组合上限 (cents) | 单手上界 (¥) | 候选 fit 率 | 日 fit 率 |",
        "|---|---|---|---|---|---|",
    ]
    for w in payload["what_if"]:  # type: ignore[union-attr]
        lines.append(
            f"| {w['scale']} | {w['nav_cents']} | {w['portfolio_cap_cents']}"
            f" | {w['single_lot_max_price_cny']} | {w['candidate_fit_rate']}"
            f" | {w['day_fit_rate']} |"
        )
    lines += [
        "",
        "## 披露与边界",
        "",
        "- fit 率为**上界**: 探针目标取包络上界 (生产 kelly 权重 < cap 时更难",
        "  fit); industry/day 槽位按单候选空槽计; 组合余量按 existing=0 计。",
        "- 价格代理 = court `signal_close`; trial 实际 sizing 价 = producer",
        "  `entry_price` (同源信号快照价, 极端情形可异)。",
        "- 反事实宇宙 = court 生产对齐全候选 (陷阱 19), 非 trial producer 实际",
        "  SELECTED 集; 与 trial decisions 库实况的对照属宿主冒烟证据。",
        "- fitted vs not-fitted 期望差未做多重比较校正; n<30 只披露不判定。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="trial 容量适配诊断 (纯披露, 只读 court 事件表)"
    )
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--nav-cents", type=int, default=DEFAULT_NAV_CENTS)
    parser.add_argument(
        "--cap-fraction", type=float, default=DEFAULT_PORTFOLIO_CAP_FRACTION
    )
    parser.add_argument(
        "--per-ticker-cents", type=int, default=DEFAULT_PER_TICKER_GROSS_CAP_CENTS
    )
    parser.add_argument(
        "--per-industry-cents",
        type=int,
        default=DEFAULT_PER_INDUSTRY_GROSS_CAP_CENTS,
    )
    parser.add_argument(
        "--per-day-cents", type=int, default=DEFAULT_PER_DAY_GROSS_CAP_CENTS
    )
    parser.add_argument(
        "--fee-ppm", type=int, default=DEFAULT_WORST_CASE_FEE_PPM
    )
    parser.add_argument("--lot-units", type=int, default=DEFAULT_LOT_UNITS)
    parser.add_argument(
        "--scales",
        type=float,
        nargs="*",
        default=list(DEFAULT_SCALES),
    )
    parser.add_argument(
        "--report-dir", type=Path, default=REPORT_DIR_DEFAULT
    )
    args = parser.parse_args(argv)

    envelope = TrialEnvelope(
        nav_cents=args.nav_cents,
        portfolio_cap_fraction=args.cap_fraction,
        per_ticker_gross_cap_cents=args.per_ticker_cents,
        per_industry_gross_cap_cents=args.per_industry_cents,
        per_day_gross_cap_cents=args.per_day_cents,
        worst_case_fee_ppm=args.fee_ppm,
        lot_units=args.lot_units,
    )
    if not args.court_table.exists():
        raise TrialCapacityFitError(
            "court_table_missing", f"event table not found: {args.court_table}"
        )
    ev = pd.read_csv(args.court_table)
    u = production_aligned(ev)
    payload = analyze(u, envelope, tuple(args.scales))
    payload["inputs"] = {
        "court_table": str(args.court_table),
        "court_rows": int(len(ev)),
        "production_aligned_rows": int(len(u)),
    }
    out_dir = args.report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{REPORT_STEM}_{date.today().strftime('%Y%m%d')}"
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    md_path.write_text(render_md(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "report": str(md_path),
                "candidate_fit_rate": payload["candidate_fit_rate"],
                "day_fit_rate": payload["day_fit_rate"],
                "single_lot_max_price_cny": payload["envelope"][
                    "single_lot_max_price_cny"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
