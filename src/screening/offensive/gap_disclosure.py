"""执行面缺口披露 (R92 Op3) — gap 判别证据到操作员执行视图的唯一通路。

R92 Op1/Op2 把 T+1 开盘缺口 (gap_t1_open) 的判别证据机制化进诊断报告:
高开 (>5%) 子集期望显著为负且罚分跨半方向稳定 — 而缺口在 9:25 竞价即可
观测, 恰是该证据发挥作用的执行时点。本模块提供:

1. gap 分桶常量与 ``gap_bucket`` 纯函数的单一定义家 (scripts/
   winrate_payoff_decomposition.py 从这里导入, 消除双定义漂移面);
2. ``gap_execution_reference`` — 从最新分解报告 JSON 只读聚合执行面参考
   (高开/低开两侧 n 加权池化 E + split-half 稳定性 + 证据日期)。

纪律: 只读诊断披露, 绝不改变计划创建/评分/仓位/退出 (披露不是行为改变,
镜像 R85 触发器状态行); 报告缺失/损坏/旧形态一律 fail-open 返回 None —
不假装有证据, 也不因诊断面缺失阻断交易流程。
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path

# 分桶边界预注册于 2026-09-01 (R92 Op1, 探索性 in-sample; 任何政策使用 =
# owner 决策 + 新数据前向验证)。左闭右开, 与 strength_bucket 同侧。
GAP_BUCKETS: tuple[tuple[float, str], ...] = (
    (-0.05, "<-5%"),
    (0.0, "-5~0"),
    (0.02, "0~2%"),
    (0.05, "2~5%"),
    (0.10, "5~10%"),
)
GAP_TOP_BUCKET = ">10%"  # ≥ 0.10 (末界右闭到无穷)
ALL_GAP_BUCKETS: tuple[str, ...] = tuple(lbl for _, lbl in GAP_BUCKETS) + (GAP_TOP_BUCKET,)
# 桶内条件判别的「高开」阈值 — 5~10% 桶下界 (R92 Op1/Op2 同源)
GAP_HIGH_THRESHOLD = 0.05
# 高开侧 = 阈值之上的桶 (池化披露用); 低开侧 = 其余非空桶
_HIGH_GAP_BUCKETS = ("5~10%", GAP_TOP_BUCKET)

# 公开单一常量 (R137 Op2 对抗审查 F1): 读取体 glob 与 freshness 异常探测面
# (daily_action) / scripts 侧跨窗口分诊扫描共用 — 字面量三处并存时 glob
# 演化会让探测面静默分叉 (一侧拒一侧看不见)。
DECOMPOSITION_REPORT_GLOB = "winrate_payoff_decomposition_*.json"
_REPORT_GLOB = DECOMPOSITION_REPORT_GLOB
# 文件名日期段形状守卫 (R109 Op2): 『字典序 = 时间序』前提只对 YYYYMMDD
# 命名成立 — glob 同前缀的 backup/editor 杂文件 ('b' > '2' 排在日期之后)
# 会被 sorted[-1] 误当最新报告, PoC 实锤可劫持披露行渲染假证据。
_DATED_SUFFIX_RE = re.compile(r"_(\d{8})$")


def report_filename_date(path: str | Path) -> str | None:
    """报告文件名日期段 (YYYYMMDD) 的单一提取谓词 (R137 Op1)。

    读取体形状守卫与 scripts 侧 typed reason 共用同一定义 — 日期提取逻辑
    漂移会让两侧行为分叉 (一侧拒一侧收)。
    """
    matched = _DATED_SUFFIX_RE.search(Path(path).stem)
    return matched.group(1) if matched else None


def _today() -> "dt.date":
    """本机今日 (可测试缝): 守卫只依赖它做未来判定, 测试可注入。"""
    return dt.date.today()


def latest_decomposition_report(
    reports_dir: str | Path = Path("data/reports"),
) -> tuple[Path, dict] | None:
    """最新分解报告的唯一读取家 (R109 Op2 收敛 gap 参考行与先验漂移行的同族读取)。

    只接受文件名日期段为 \\d{8} 的报告 (形状守卫); 新鲜度 = 日期字典序最大者。
    文件缺失/不可读/非法 JSON/顶层非对象 → None (fail-open, 不假装有证据);
    损坏的最新报告不回退旧报告 — 以 None 示警, 不以陈旧数字冒充当前证据。

    未来日期绊线 (R137 Op1, R136 Op2 登记开放项收口): 选中报告日期晚于今日
    即拒绝 — 合法管道只在当日写报告, 未来日期只能来自手工放置/时钟错乱;
    与损坏同款不回退次新 (目录处于异常状态时静默展示旧证据 = 假冒当前)。
    """
    return _latest_dated_report(reports_dir, _REPORT_GLOB)


def _latest_dated_report(
    reports_dir: str | Path,
    report_glob: str,
) -> tuple[Path, dict] | None:
    """按日期段形状守卫取字典序最新报告 (两读取家共享实现, 防漂移)。"""
    directory = Path(reports_dir)
    try:
        dated = sorted(
            path
            for path in directory.glob(report_glob)
            if report_filename_date(path) is not None
        )
    except OSError:
        return None
    if not dated:
        return None
    path = dated[-1]
    report_date = report_filename_date(path) or ""
    if report_date > _today().strftime("%Y%m%d"):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return path, payload


def future_dated_report_day(
    reports_dir: str | Path = Path("data/reports"),
    glob_pattern: str = DECOMPOSITION_REPORT_GLOB,
    today: "dt.date | None" = None,
) -> str | None:
    """目录内最新未来日期报告的文件名日期; 无则 None (毒化探测, R140 Op3)。

    未来日期守卫下沉共享读取体 (R137 Op1) 后证据消费者读到 None 不回退 —
    本探测让消费行区分两种 None 形态: 目录缺失/纯损坏 (维持行缺席 fail-open
    家族纪律) 与『目录被未来日期文件占据』(毒化/时钟故障, typed 告警显形,
    操作员必须看得见哪一行证据被谁挡住)。只看文件名日期不解析内容, 与
    读取体共用 report_filename_date 单一谓词; today 注入锚与渲染同钟
    (R127 测试确定性 / R137 Op2 两钟分叉纪律); glob 参数覆盖分解报告与
    signal_day_cohort 两报告族。
    """
    base = Path(reports_dir)
    try:
        dates = [
            report_filename_date(p) for p in base.glob(glob_pattern)
        ]
    except OSError:
        return None
    wall_today = today if today is not None else _today()
    today_text = wall_today.strftime("%Y%m%d")
    future = [d for d in dates if d is not None and d > today_text]
    return max(future) if future else None


def poisoned_report_clause(
    reports_dir: str | Path = Path("data/reports"),
    glob_pattern: str = DECOMPOSITION_REPORT_GLOB,
    today: "dt.date | None" = None,
    label: str = "分解报告",
) -> str | None:
    """消费行毒化告警子句的单一措辞源 (R140 Op3); 非毒化 → None。

    四个证据行 (先验漂移/入选质量构成/执行面缺口参考/信号日 cohort 语境)
    的未来日期毒文件 typed 告警共用同一段措辞 — 措辞漂移会让操作员把
    同一异常当成四种故障。
    """
    day = future_dated_report_day(reports_dir, glob_pattern, today)
    if day is None:
        return None
    return (
        f"{label}目录被未来日期文件占据（最新 {day}）— "
        "守卫拒绝读取（核查文件名或时钟）"
    )


# 公开单一常量 (R140 Op3: cohort 语境行毒化探测需同源 glob — 字面量复制
# 会让探测面与读取面在 glob 演化时分叉, DECOMPOSITION_REPORT_GLOB 同款纪律)
COHORT_REPORT_GLOB = "signal_day_cohort_*.json"
_COHORT_REPORT_GLOB = COHORT_REPORT_GLOB

# cohort 规模分桶 (R123 Op1 定义, R125 Op3 上移单一实现家): 左闭右闭日数
# 边界, 显式边界不玩 cut 花活。脚本 (scripts/btst_signal_day_cohort) 与
# 操作员渲染行共用 — 两侧口径不可漂移。
COHORT_BUCKET_EDGES: tuple[tuple[int, int], ...] = (
    (1, 1),
    (2, 3),
    (4, 9),
    (10, 19),
    (20, math.inf),
)
COHORT_BUCKET_LABELS: tuple[str, ...] = ("1", "2-3", "4-9", "10-19", "20+")


def cohort_size_bucket(n_days_members: int) -> str:
    """cohort 规模 (当日事件数) → 分桶标签。

    非整数/非正数 fail-closed (bool 是 int 子类, 显式拒) — 分桶口径由
    构造保证, 绝不静默归桶。
    """
    if not isinstance(n_days_members, int) or isinstance(n_days_members, bool):
        raise TypeError(f"cohort size must be int, got {type(n_days_members).__name__}")
    if n_days_members <= 0:
        raise ValueError(f"cohort size must be positive, got {n_days_members}")
    for (lo, hi), label in zip(COHORT_BUCKET_EDGES, COHORT_BUCKET_LABELS):
        if lo <= n_days_members <= hi:
            return label
    raise ValueError(f"cohort size {n_days_members} outside predefined edges")


def latest_signal_day_cohort_report(
    reports_dir: str | Path = Path("data/reports"),
) -> tuple[Path, dict] | None:
    """最新信号日 cohort 分解报告的唯一读取家 (R125 Op3)。

    与 latest_decomposition_report 同构 (形状守卫/字典序新鲜/损坏 None
    不回退旧报告 — 不以陈旧数字冒充当前证据), 经 _latest_dated_report
    单一实现只换 glob。
    """
    return _latest_dated_report(reports_dir, _COHORT_REPORT_GLOB)


# 公开单一常量 (R137 Op2 同纪律): 读取体 glob 与渲染/测试同源, 字面量多处
# 并存时 glob 演化会让各面静默分叉 (一侧拒一侧看不见)。
EXIT_ANATOMY_REPORT_GLOB = "exit_anatomy_*.json"
_EXIT_ANATOMY_GLOB = EXIT_ANATOMY_REPORT_GLOB

# 止损当期方向读数承认的 regime 标签集 (与 regime_history 三态同源;
# unknown/缺失 = 数据缺口, 不冒充证据)。
_STOP_DIRECTION_REGIME_LABELS = ("crisis", "normal", "risk_off")

# 止损档键形状 ("−5%" / "-12.5%"); 形状外的键不进最佳档选择 (防畸形键冒充)。
_STOP_TIER_RE = re.compile(r"^-?\d+(?:\.\d+)?%$")


def latest_exit_anatomy_report(
    reports_dir: str | Path = Path("data/reports"),
) -> tuple[Path, dict] | None:
    """最新退出解剖报告的唯一读取家 (R181 Op1)。

    与 latest_signal_day_cohort_report 同构 (形状守卫/字典序新鲜/未来日期
    拒绝/损坏 None 不回退旧报告 — 不以陈旧数字冒充当前证据), 经
    _latest_dated_report 单一实现只换 glob。
    """
    return _latest_dated_report(reports_dir, _EXIT_ANATOMY_GLOB)


def _finite_number(value: object) -> bool:
    """有限数值谓词 (bool 显式排除; NaN/inf 排除) — 本模块局部守卫。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _valid_sample_count(value: object) -> bool:
    """样本计数谓词 (int 且非 bool 且 >0) — 0 行桶不能冒充证据 (R181 Op2
    n_included=0 拒绝同族); bool 是 int 子类须显式排除。"""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


# R188 Op1: split_half.pooled (聚合罚分跨半读数) 的消费面字段 — 执行面行文
# 自身的问题是聚合层 (『高开>5% 子集历史期望』), 该块是其直答读数; 与分桶
# 合取 verdict (split_stable, R15 镜像) 并列披露互不替代。
_POOLED_PENALTY_NUMBER_FIELDS = (
    "penalty_first",
    "penalty_second",
    "e_hi_first",
    "e_hi_second",
)
_POOLED_PENALTY_COUNT_FIELDS = ("n_hi_first", "n_hi_second")


def parse_pooled_penalty(raw: object) -> dict[str, object] | None:
    """split_half.pooled 严格形状守卫 (R188 Op1) — 全字段合法才解析, 否则 None。

    pooled 是纯增量键 (旧报告缺席 → None); 任一字段畸形 (bool 毒化/非有限
    数/缺失/负计数) → 整块拒绝 (半真披露比无披露更有害), 消费行子句省略。
    """
    if not isinstance(raw, dict):
        return None
    consistent = raw.get("consistent")
    if not isinstance(consistent, bool):
        return None
    parsed: dict[str, object] = {"consistent": consistent}
    for key in _POOLED_PENALTY_NUMBER_FIELDS:
        value = raw.get(key)
        if not _finite_number(value):
            return None
        parsed[key] = float(value)  # type: ignore[arg-type]
    for key in _POOLED_PENALTY_COUNT_FIELDS:
        value = raw.get(key)
        # R188 Op2 P09b 钉子: >0 (镜像 _valid_sample_count『0 行桶不能冒充
        # 证据』) — consistent=bool 与 count=0 是自相矛盾载荷 (生产者契约:
        # consistent 非 None 蕴含两侧 n≥MIN_CELL_N), 报告损坏/篡改形态整块拒绝。
        if not _valid_sample_count(value):
            return None
        parsed[key] = value
    return parsed


def pooled_penalty_body(pooled: object) -> str | None:
    """聚合罚分读数正文 (R189 Op1) — 执行面子句与 MD 渲染面 (render_md
    split-half 节) 的单一实现, 两表面同源防漂移; pooled 缺席/畸形 → None
    (半真披露比无披露更有害, parse_pooled_penalty 同款纪律)。"""
    parsed = parse_pooled_penalty(pooled)
    if parsed is None:
        return None
    same = "同号" if parsed["consistent"] else "异号"
    return (
        f"聚合罚分两半 {parsed['penalty_first'] * 100:+.2f}pp"
        f"/{parsed['penalty_second'] * 100:+.2f}pp {same}"
        f"（高开子集期望 {parsed['e_hi_first']:+.2%}/{parsed['e_hi_second']:+.2%}"
        f" · n {parsed['n_hi_first']}/{parsed['n_hi_second']}）"
    )


def pooled_penalty_clause(pooled: object) -> str:
    """执行面行聚合罚分子句 (R188 Op1) — pooled 缺席/畸形 → 空串 (行逐字节不变)。

    同号/异号措辞由 consistent bool 驱动; 判读语义属 owner (宪法 #2),
    子句只把聚合层读数与 R15 分桶 verdict 并列显形。正文单一实现见
    pooled_penalty_body (R189 Op1: MD 渲染面同源消费, 防两表面漂移)。
    """
    body = pooled_penalty_body(pooled)
    return f" · {body}" if body else ""


def best_stop_tier(
    grid: object,
) -> tuple[str, float, dict] | None:
    """止损反事实网格的最佳档位选择 (结构化单一实现, R193 Op1)。

    档位深度升序遍历 + 严格大于: 平局取更浅档, 与插入序无关 (R181 Op2
    P-a: 实现曾按 dict 插入序遍历, 与 docstring 声称的确定性平局语义不符;
    形状外键先剔除再排序, 排序键不做防御。档标签是负百分比, 浅档=|深度|
    更小, 排序键取绝对值 — 数值升序会把 -12% 排在 -5% 之前)。

    网格非 dict/为空、无形状合法档、或全部档 Δ 非有限 → None (不假装有
    最佳档)。消费面: stop_direction_clause (渲染) 与
    scripts/stop_loss_enablement_pack.py (两面装配) 同源。
    """
    if not isinstance(grid, dict) or not grid:
        return None
    best_tier: str | None = None
    best_delta: float | None = None
    best_entry: dict | None = None
    shaped = [
        (tier, entry)
        for tier, entry in grid.items()
        if isinstance(tier, str)
        and _STOP_TIER_RE.match(tier)
        and isinstance(entry, dict)
    ]
    for tier, entry in sorted(
        shaped, key=lambda kv: abs(float(kv[0].rstrip("%")))
    ):
        delta = entry.get("delta_vs_base")
        if not _finite_number(delta):
            continue
        if best_delta is None or delta > best_delta:
            best_tier, best_delta, best_entry = tier, float(delta), entry
    if best_tier is None or best_entry is None or best_delta is None:
        return None
    return best_tier, best_delta, best_entry


def stop_direction_clause(
    payload: object,
    regime_label: object,
    report_date: str,
) -> str | None:
    """项 5 当期止损方向子句 (R181 Op1) — 夜刷 exit_anatomy 止损反事实的操作员面。

    修复的失实: 操作员止损启用条件行把 owner 指向 backtest_exit_strategies.py
    「确认当期方向」, 而该工具输入冻结在 journal 恢复样本 (2026-01-15→07-06),
    按构造回答不了「当期」; 当期方向证据是夜刷 btst_exit_anatomy 的
    production×regime 止损反事实网格 (诚实成交语义: 跳空按 open 成交)。

    口径如实标注: by_regime 桶建在当前表全候选上 (非 production_aligned
    过滤), 措辞固定「生产表/<label>/全候选」; as-of 日期自暴露 (文件名日期段
    由调用方透传, 陈旧可见不冒充)。最佳档 = 有限 Δ 中最大者 (键按档位深度
    升序遍历 + 严格大于, 平局取更浅档, 确定); 键非「-N%」形态或 Δ 非有限的
    档跳过。

    纯函数 + fail-open (R85/R115/R119 家族): payload/桶/网格形状不符、基准
    或最佳 Δ 非有限、n 缺失或 ≤0 (0 行桶不能冒充证据)、report_date 空
    (无日期的证据声明不渲染)、标签不在三态集 → None (不假装有证据, 渲染侧
    整子句省略, 绝不渲染部分垃圾)。
    """
    if regime_label not in _STOP_DIRECTION_REGIME_LABELS:
        return None
    if not report_date or not isinstance(report_date, str):
        return None
    if not isinstance(payload, dict):
        return None
    production = payload.get("production")
    if not isinstance(production, dict):
        return None
    by_regime = production.get("by_regime")
    if not isinstance(by_regime, dict):
        return None
    bucket = by_regime.get(regime_label)
    if not isinstance(bucket, dict):
        return None
    n_total = bucket.get("n_included")
    if not _finite_number(n_total) or n_total <= 0:
        return None
    base = bucket.get("base")
    base_mean = base.get("mean_net") if isinstance(base, dict) else None
    if not _finite_number(base_mean):
        return None
    grid = bucket.get("stop_grid")
    if not isinstance(grid, dict) or not grid:
        return None
    found = best_stop_tier(grid)
    if found is None:
        return None
    best_tier, best_delta, best_entry = found
    best_mean = best_entry.get("mean_net")
    n_stopped = best_entry.get("n_stopped")
    n_gap = best_entry.get("n_gap_through")

    def _pct(value: float) -> str:
        return f"{value * 100:+.2f}%"

    def _pp(value: float) -> str:
        return f"{value * 100:+.2f}pp"

    clause = (
        f"当期方向（exit_anatomy {report_date} · 生产表/{regime_label}/全候选，"
        f"n={int(n_total)}）：基准 {_pct(base_mean)} · 最佳止损档 {best_tier}"
        f"（Δ{_pp(best_delta)}"
    )
    if _finite_number(best_mean):
        clause += f"，档内 {_pct(best_mean)}"
    if _finite_number(n_stopped):
        clause += f"，触发 {int(n_stopped)}/{int(n_total)}"
    if _finite_number(n_gap):
        clause += f"，跳空穿越 {int(n_gap)}"
    clause += "）"
    return clause


# 公开单一常量 (R137 Op2 同纪律): 读取体 glob 与渲染/测试同源, 字面量多处
# 并存时 glob 演化会让各面静默分叉 (一侧拒一侧看不见)。
RUN_CONDITIONING_REPORT_GLOB = "regime_blocked_run_conditioning_*.json"
_RUN_CONDITIONING_GLOB = RUN_CONDITIONING_REPORT_GLOB


def latest_run_conditioning_report(
    reports_dir: str | Path = Path("data/reports"),
) -> tuple[Path, dict] | None:
    """最新 regime 阻断连跑条件化报告的唯一读取家 (R182 Op1)。

    与 latest_exit_anatomy_report 同构 (形状守卫/字典序新鲜/未来日期
    拒绝/损坏 None 不回退旧报告 — 不以陈旧数字冒充当前证据), 经
    _latest_dated_report 单一实现只换 glob。
    """
    return _latest_dated_report(reports_dir, _RUN_CONDITIONING_GLOB)


def reentry_readings_clause(payload: object, report_date: str) -> str | None:
    """d1 重入邻近度当期读数子句 (R182 Op1) — 夜刷阻断连跑条件化的操作员面。

    修复的不对称: R176 重入行把 owner 指向夜刷 regime_blocked_run_conditioning
    报告看「当期数字」, 行内只渲染 R168 注册证据静态值 (as-of 自暴露) — 与
    R181 项 5 止损方向当期化建立的原则相反 (判定时刻判定输入应行内可见)。
    crisis↔normal 翻转期 (2026-09) 重入决策现场每周出现, 首个 normal 信号日
    操作员不应再手动打开夜刷报告。

    口径如实标注: 读数是 t10 净口径 (毛收益 − 往返 0.65%, 工具同式);
    配对差 = blip − run (正值 = run 罚分在场); as-of 日期自暴露 (文件名
    日期段由调用方透传, 陈旧可见不冒充)。

    纯函数 + fail-closed 形状守卫 (R85/R115/R119 家族): payload/tables/d1
    双行形状不符、n 缺失或 ≤0 或 bool (0 行不能冒充证据)、E/胜率非有限、
    配对差 CI 缺失或非有限或 ci_low > ci_high (结构非法)、delta 池计数与
    组行 n 不一致 (键↔内容交叉, R44/R47 家族)、report_date 空 (无日期的
    证据声明不渲染) → None (渲染侧回退注册证据静态行, 不渲染部分垃圾)。
    split-half 判读是可选段: consistent 非 bool (缺位/畸形) → 该段省略,
    其余读数照常。
    """
    if not report_date or not isinstance(report_date, str):
        return None
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        return None
    t10 = tables.get("t10")
    if not isinstance(t10, dict):
        return None
    run_row = t10.get("d1_run")
    blip_row = t10.get("d1_blip")
    if not isinstance(run_row, dict) or not isinstance(blip_row, dict):
        return None
    n_run = run_row.get("n")
    n_blip = blip_row.get("n")
    if not _valid_sample_count(n_run) or not _valid_sample_count(n_blip):
        return None
    run_e = run_row.get("expectancy")
    run_wr = run_row.get("winrate")
    blip_e = blip_row.get("expectancy")
    blip_wr = blip_row.get("winrate")
    if not (
        _finite_number(run_e)
        and _finite_number(run_wr)
        and _finite_number(blip_e)
        and _finite_number(blip_wr)
    ):
        return None
    run_deltas = payload.get("run_deltas_t10")
    if not isinstance(run_deltas, dict):
        return None
    delta = run_deltas.get("d1_run_vs_blip")
    if not isinstance(delta, dict):
        return None
    ci_low = delta.get("ci_low")
    ci_high = delta.get("ci_high")
    if not _finite_number(ci_low) or not _finite_number(ci_high):
        return None
    if ci_low > ci_high:
        return None
    # 键↔内容交叉 (R44/R47 家族): 配对差声明的池计数与组行 n 分叉 = 工件
    # 内部矛盾, 整子句拒绝不假装 (渲染矛盾读数比不渲染更有害)。
    if delta.get("n_run") != n_run or delta.get("n_blip") != n_blip:
        return None
    split_token = ""
    split_half = payload.get("split_half_d1")
    if isinstance(split_half, dict) and isinstance(
        split_half.get("consistent"), bool
    ):
        verdict = "跨半一致" if split_half["consistent"] else "跨半翻转"
        split_token = f" · split-half {verdict}"

    def _pct(value: float) -> str:
        return f"{value * 100:+.2f}%"

    def _wr(value: float) -> str:
        return f"{value * 100:.1f}%"

    return (
        f"当期读数（夜刷 regime_blocked_run_conditioning {report_date} · "
        f"t10 净口径）：d1_run E={_pct(run_e)}/胜率 {_wr(run_wr)}"
        f"（n={int(n_run)}）· d1_blip E={_pct(blip_e)}/{_wr(blip_wr)}"
        f"（n={int(n_blip)}）· 配对差 CI90 "
        f"[{_pct(ci_low)},{_pct(ci_high)}]（正值=run 罚分）{split_token}"
    )


# R184 Op1: 时代外验报告 glob 同纪律 (公开常量与读取家/渲染/测试同源,
# 字面量多处并存时 glob 演化会让各面静默分叉)。
CROSS_ERA_REPORT_GLOB = "regime_run_cross_era_validation_*.json"
_CROSS_ERA_GLOB = CROSS_ERA_REPORT_GLOB


def latest_cross_era_report(
    reports_dir: str | Path = Path("data/reports"),
) -> tuple[Path, dict] | None:
    """最新 cross-era 时代外验报告的唯一读取家 (R184 Op1)。

    与 latest_run_conditioning_report 同构 (形状守卫/字典序新鲜/未来日期
    拒绝/损坏 None 不回退旧报告 — 不以陈旧数字冒充当前证据), 经
    _latest_dated_report 单一实现只换 glob。
    """
    return _latest_dated_report(reports_dir, _CROSS_ERA_GLOB)


def cross_era_verdict_clause(payload: object, report_date: str) -> str | None:
    """重入决策锚时代外验当期读数子句 (R184 Op1) — 夜刷 cross-era 的操作员面。

    R183 Op1 把 regime_run_cross_era_validation 接入夜刷链后, R168 d1 边界
    的时代外验证据 (当前/早期双表装配) 当前侧每夜保鲜, 但重入决策点上操作员
    只看到阻断连跑当期读数 (R182 Op1) 与注册证据静态锚 — 时代外验 verdict
    仍只活在磁盘报告, 判定时刻不可见 (R182 Op1 所修不对称的同族第三腿)。

    口径如实标注: 点罚分 = blip E − run E (正值 = run 罚分在场, 工具
    _point_penalty 同式); 陈述是工具机械谓词装配的三形态 (独立时代支持 /
    仅当前时代 / 不可判定), 本子句原样透传不改写判定语义; as-of 日期自
    暴露 (文件名日期段由调用方透传, 陈旧可见不冒充)。

    纯函数 + fail-closed 形状守卫 (R85/R115/R119/R182 家族): payload 非
    dict、verdict 缺失或非 dict、statement 非 str 或空、
    d1_penalty_sign_consistent 非 bool (判定谓词缺席不冒充)、
    early_ci_excludes_current_point 非 bool 且非 None、d1_point_penalty
    缺失或非 dict、current/early 非 None 且非有限数 (bool 亦拒 — True==1
    会冒充 +100.00%)、report_date 空 → None (渲染侧子句静默省略, 不渲染
    部分垃圾)。点罚分 None (组 n<MIN_CELL_N) 合法, 渲染 '—' (工具 _fmt
    同款诚实缺省)。
    """
    if not report_date or not isinstance(report_date, str):
        return None
    if not isinstance(payload, dict):
        return None
    verdict = payload.get("verdict")
    if not isinstance(verdict, dict):
        return None
    statement = verdict.get("statement")
    if not isinstance(statement, str) or not statement:
        return None
    sign_consistent = verdict.get("d1_penalty_sign_consistent")
    if not isinstance(sign_consistent, bool):
        return None
    excludes = verdict.get("early_ci_excludes_current_point")
    if excludes is not None and not isinstance(excludes, bool):
        return None
    points = payload.get("d1_point_penalty")
    if not isinstance(points, dict):
        return None

    def _point(value: object) -> str | None:
        if value is None:
            return "—"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(float(value)):
            return None
        return f"{float(value) * 100:+.2f}%"

    cur_token = _point(points.get("current"))
    early_token = _point(points.get("early"))
    if cur_token is None or early_token is None:
        return None
    sign_token = "方向一致" if sign_consistent else "方向不一致"
    return (
        f"时代外验（夜刷 regime_run_cross_era_validation {report_date} · "
        f"当前点罚分 {cur_token} · 早期点罚分 {early_token} · "
        f"两时代 {sign_token}）：{statement}"
    )


def gap_bucket(gap: float | None) -> str:
    """T+1 开盘缺口分桶 — 左闭右开, 缺失诚实 unknown (不假装知道)。"""
    if gap is None or (isinstance(gap, float) and math.isnan(gap)):
        return "unknown"
    g = float(gap)
    for bound, label in GAP_BUCKETS:
        if g < bound:
            return label
    return GAP_TOP_BUCKET


def gap_execution_reference(
    reports_dir: str | Path = Path("data/reports"),
) -> dict[str, object] | None:
    """从最新分解报告聚合执行面缺口参考; 证据不可得 → None (fail-open)。

    聚合口径 (与报告 gap_anatomy 同源): 高开侧 = 5~10% ∪ >10% 两桶的 n
    加权池化期望 (Σn·E/Σn), 低开侧 = 其余非空桶; n 为 0 的桶跳过, 任一
    侧无样本 → None (不渲染半边缺失的参考)。split_stable = split-half
    可判定桶方向全一致 (R15 判据镜像; False 时操作员行如实措辞)。
    """
    found = latest_decomposition_report(reports_dir)
    if found is None:
        return None
    _path, payload = found
    universes = payload.get("universes") if isinstance(payload, dict) else None
    aligned = universes.get("production_aligned") if isinstance(universes, dict) else None
    gap = aligned.get("gap_anatomy") if isinstance(aligned, dict) else None
    if not isinstance(gap, dict) or gap.get("available") is False:
        return None
    buckets = gap.get("buckets")
    if not isinstance(buckets, list):
        return None
    hi_n = hi_we = lo_n = lo_we = 0.0
    for cell in buckets:
        if not isinstance(cell, dict):
            continue
        n = cell.get("n")
        e = cell.get("expectancy")
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            continue
        if not isinstance(e, (int, float)) or isinstance(e, bool):
            continue
        if cell.get("bucket") in _HIGH_GAP_BUCKETS:
            hi_n += n
            hi_we += n * e
        else:
            lo_n += n
            lo_we += n * e
    if hi_n == 0 or lo_n == 0:
        return None
    split = gap.get("split_half")
    split_stable: bool | None = None
    if isinstance(split, dict):
        judgable = split.get("judgable_count")
        consistent = split.get("consistent_count")
        if isinstance(judgable, int) and isinstance(consistent, int) and judgable > 0:
            split_stable = consistent == judgable
    # R188 Op1: 聚合罚分块严格守卫消费 — 缺席 (旧报告)/畸形 → None, 消费行
    # 子句省略 (fail-open 接线家族纪律, 与修复前逐字节一致)。
    pooled_ref: dict[str, object] | None = None
    if isinstance(split, dict):
        parsed = parse_pooled_penalty(split.get("pooled"))
        if parsed is not None:
            pooled_ref = parsed
    total_n = None
    horizons = aligned.get("horizons")
    if isinstance(horizons, dict):
        rows = horizons.get("t10")
        if isinstance(rows, list):
            all_row = next((r for r in rows if isinstance(r, dict) and r.get("group") == "ALL"), None)
            if all_row is not None and isinstance(all_row.get("n"), int):
                total_n = all_row["n"]
    # R141 Op3: 证据窗口末端穿透 — payload.court_window.end 是数据内容
    # 真相 (事件表 signal_date max), 与 evidence_date (报告构建日) 是两个
    # 事实; 旧报告缺字段 → None (消费行回退构建日语义, 不虚构覆盖)。
    window_end = None
    court_window = payload.get("court_window")
    if isinstance(court_window, dict):
        value = court_window.get("end")
        if isinstance(value, str) and len(value) == 8 and value.isdigit():
            window_end = value
    return {
        "evidence_date": _path.stem.rsplit("_", 1)[-1],
        "window_end": window_end,
        "n_hi": int(hi_n),
        "e_hi": hi_we / hi_n,
        "n_lo": int(lo_n),
        "e_lo": lo_we / lo_n,
        "split_stable": split_stable,
        "pooled": pooled_ref,
        "total_n": total_n,
    }
