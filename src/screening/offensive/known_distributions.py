"""已冻结的 setup 先验分布 (披露层) + 各常量的样本出处。

这些分布是 --daily-action 的"先验"披露。⚠ 仓位不消费这些数字:
仓位 = setup_max_pct × drawdown_factor × strength_factor (daily_action 的
kelly_pct 路径; 2026-08-14 regime 加仓移除时装饰性 Kelly 计算已删) —
先验只进展示 (先验行/期望披露) 与 setup 注册验证, 不进仓位链。

⚠ 出处分层 (2026-08-19 owner 批准重校准入册, 新证据世代):
BTST T+10 与 OversoldBounce T+5 先验已从 court 全候选重放重校准 —
与被复核策略候选宇宙一致 (含退市者快照、T+1 开盘买 + 30bps/边滑点 +
5bps 卖出印花税), 公式指纹钉在 manifest, 重算脚本口径可复验。
BTST T+8 已于 2026-08-22 补齐 court 重校准 (owner 批准, 见下块注释);
不得再作为当前口径引用。旧值 (2026-07-12 连续涨停样本、未扣费) 移入
下方历史校准记录。

⚠ 重要: 这些分布来自历史回放, 不是未来承诺。setup IC 会衰减, 需定期重测
(重验工具 scripts/review_btst_prior_court.py, --check 断言恒跑)。

历史校准记录 (审计线索, 非当前生效值的出处):
- Phase 0 btst_breakout @ T+10: cv=1.81, winrate=54.2%, E=+3.38%, n=1762, IC=0.126
  → 本地数据不可复现 (AGENTS.md trap 4), 仅作历史审计线索
- BTST T+8/T+10 @ 2026-07-12: 626 票、连续涨停样本、未扣费 (T10: wr=58.78%,
  E=+6.57%; T8: wr=59.4%, E=+5.43%) — 连续涨停人群与生产首板触发错配且未扣费;
  2026-08-19 court 重验显示该口径较生产对齐宇宙虚高 E ~6pp/胜率 ~12pp,
  owner 批准后 T10 由 court 值取代 (T8 保留旧值仅作回测兼容, 已标注)
- oversold_bounce @ 2026-07-11: journal 成交子集 59 笔 (E=+0.34%, cv=0.96)
  → 2026-08-19 court 全候选复核 (n=2,205, T+5 净 E=-0.40%, CI90 下界 -1.21%
  ≤ 0, 无正 alpha) 后由 court 值取代; OB 维持默认暂停

执行口径参考 (BTST, 与重校准后先验同源 — 供展示层脚注披露):
court 全候选生产对齐宇宙 (2025-07-02→2026-08-18, n=1464): 期望 +0.56% ·
胜率 46.4% · CI90 [-1.30%, +2.39%]。journal 执行重建 (n=130, +3.41%/57%)
是成交子集 — 按 trap 19 不可作证据宇宙, 仅保留为历史审计线索。
重验工具: scripts/review_btst_prior_court.py (三视图: 生产对齐宇宙/
排除行披露/时间切片), 产物 data/reports/btst_prior_court_recheck_*.md。
"""

from __future__ import annotations

from src.screening.offensive.statistics import Distribution

# BTST 突破 T+8 — 2026-08-22 owner 批准补齐重校准 (同 2026-08-19 T+10
# court 重校准世代的收尾): court 全候选生产对齐宇宙 (与 T+10 同过滤链),
# T+1 开盘买 + T+8 开盘卖, 净口径已扣 30bps/边滑点 + 5bps 卖出印花税;
# 聚类 bootstrap CI90 (n_boot=3000, seed=20260818, 与 review 同参数可复验);
# IC = 日内 trigger_strength×gross_ret_t8 Spearman 均值 (84 个 ≥5 事件日).
# 旧值 (2026-07-12 的 626 票连续涨停样本、未扣费, E=+5.43%/wr=59.4%,
# 自 T+10 全池按 T+k 曲线校准 E×1.10/avg_loss×0.85) 虚高 ~5pp, 仅保留为
# 历史审计线索. T+8 E 比 T+10 弱 (+0.18% vs +0.56%), CI 跨 0 — 与
# "持有更久捕获突破延续" 的 setup 语义一致, 披露层如实呈现.
BTST_BREAKOUT_T8 = Distribution(
    n=1464,
    winrate=0.4577,
    avg_gain=0.1180,
    avg_loss=-0.0963,
    convexity_ratio=1.03,
    expected_return=0.0018,
    ci_low=-0.0155,
    ci_high=0.0174,
    ic=0.0748,
    provenance="court 全候选生产对齐宇宙 n=1464 · 2025-07→2026-08 · T+1 开盘+真实成本 · 2026-08-22 owner 批准补齐 (同 2026-08-19 T+10 重校准世代)",
)

# BTST 突破 T+10 — 2026-08-19 owner 批准重校准 (新证据世代), court 全候选重放:
# 生产对齐宇宙 (fillable & 非 gate_blocked & 非 degraded/ST/行业缺失/排除名单/
# price≥3), 2025-07-02→2026-08-18, T+1 开盘买 + T+10 开盘卖, 净口径已扣
# 30bps/边滑点 + 5bps 卖出印花税; 按信号日聚类 bootstrap CI90 (n_boot=3000,
# seed=20260818, 与 review_btst_prior_court 同参数可复验); IC = 日内
# trigger_strength×gross_ret_t10 Spearman 均值 (87 个 ≥5 事件日).
# 取代 2026-07-12 连续涨停口径 (wr 58.78%→46.45%, E +6.57%→+0.56%) —
# 旧值虚高主因: 连续涨停人群错配 + 未扣费.
BTST_BREAKOUT_T10 = Distribution(
    n=1464,
    winrate=0.4645,
    avg_gain=0.1344,  # 盈利端净均值 +13.44%
    avg_loss=-0.1062,  # 亏损端净均值 -10.62%
    convexity_ratio=1.10,  # 盈亏比×概率比 — 已低于旧口径的 2.53
    expected_return=0.0056,  # +0.56% (净, 已扣费)
    ci_low=-0.0130,  # CI90 跨 0 → 期望为正但单期不显著
    ci_high=0.0236,
    ic=0.0964,
    provenance="court 全候选生产对齐宇宙 n=1464 · 2025-07→2026-08 · T+1 开盘+真实成本 · 2026-08-19 owner 批准重校准",
)

# OversoldBounce 超跌反弹 T+5 — 2026-08-19 owner 批准重校准 (新证据世代):
# court 全候选重放 (scripts/ob_court_build.py, 生产 OversoldBounceSetup 原样
# import), 全触发候选 fillable, 2025-07-02→2026-08-18, T+1 开盘买 + T+5 开盘卖,
# 净口径已扣 65bps; 聚类 bootstrap CI90 同参数; IC = 日内强度×收益 Spearman
# 均值 (118 个 ≥5 事件日). 取代 2026-07-11 journal 成交子集 (59 笔, trap 19
# 选择偏差口径). E 为负且 CI 跨 0 → 无正 alpha, 维持默认暂停.
OVERSOLD_BOUNCE_T5 = Distribution(
    n=2205,
    winrate=0.4639,
    avg_gain=0.0786,  # +7.86%
    avg_loss=-0.0754,  # -7.54%
    convexity_ratio=0.90,  # <1 → 无凸性, Kelly f* < 0
    expected_return=-0.0040,  # -0.40% (净, 已扣费)
    ci_low=-0.0123,  # CI90 跨 0 (上界 +0.38%) → 无显著 alpha, 方向为负
    ci_high=0.0038,
    ic=0.0056,
    provenance="court 全候选 n=2205 · 2025-07→2026-08 · T+1 开盘+真实成本 · 2026-08-19 owner 批准重校准 · 维持暂停",
)

# 已知分布注册表: {(setup_name, horizon): Distribution}
# --daily-action 查这个表拿先验分布
# 生产执行合约固定 T+10 (T+8 是历史 horizon, 仅回测兼容)
KNOWN_DISTRIBUTIONS: dict[tuple[str, int], Distribution] = {
    ("btst_breakout", 8): BTST_BREAKOUT_T8,
    ("btst_breakout", 10): BTST_BREAKOUT_T10,   # 保留旧 key 供回测兼容
    ("oversold_bounce", 5): OVERSOLD_BOUNCE_T5,
}


def get_known_distribution(setup_name: str, horizon: int) -> Distribution | None:
    """查已知分布; 未验证的 setup 返回 None (--daily-action 会拒绝出信号)."""
    return KNOWN_DISTRIBUTIONS.get((setup_name, horizon))


# 执行口径参考 (展示层脚注用): 主锚 = court 全候选生产对齐宇宙
# (scripts/review_btst_prior_court.py 三视图), trap 19 纪律: journal 成交子集
# 不可作证据宇宙, 只保留为标注过的审计线索. 2026-08-19 重校准后先验与该口径
# 同源 — 脚注陈述对齐关系而非差距.
BTST_EXECUTABLE_REFERENCE = (
    "执行口径参考（court 全候选生产对齐宇宙，2025-07→2026-08，"
    "T+1 开盘+真实成本，n=1464）：期望 +0.56% · 胜率 46.4% — "
    "先验已按该口径重校准（2026-08-19 owner 批准，新证据世代）"
    "（journal 成交子集 n=130 +3.4% 仅作历史审计：成交选择偏差，非证据宇宙）"
)
