# 统一日期解析：17:00 信号日规则 + `--end-date` 覆盖 + 清理残留报告

## 背景与根因

你跑 `--daily-action` 时触发了 staleness 保护：`auto_screening_20260709.json`（报告日）领先于 price_cache 最新日 `20260708`。

根因：那次 `--auto` 在 07-09 **01:21** 跑出，而 17:00 逻辑在当天 **02:12**（commit `c3adf0e3`）才引入。凌晨跑的旧逻辑用"今天=0709"生成了报告，比 price_cache 领先一天。

**`--auto` 主路径的 17:00 逻辑现已正确工作**（已验证：现在 09:11 → 默认 `2026-07-08`）。但仍有三处盲区 + 一个 `--daily-action` 不感知时间的缺陷。本次全部修复。

## 新建共享 helper：`src/utils/date_utils.py`

新增函数 `resolve_signal_date(*, now: datetime | None = None, ready_hour: int | None = None) -> str`：

- 返回 **YYYYMMDD** 格式（紧凑，对齐 `trade_date` 约定）。
- `now` 默认 `datetime.now()`（本地墙钟，保持与现有 `_resolve_default_end_date` 一致）。
- `ready_hour` 默认读 `DATA_READY_HOUR` 环境变量（非法回退 17）。
- 逻辑：`now.hour < ready_hour` → 昨天；否则今天。
- 纯 stdlib，零重依赖。同时新增 `resolve_signal_date_iso(...)` 返回 `YYYY-MM-DD`（供 `input.py` 复用，避免重复格式化）。

## 改动 1：`src/cli/input.py` 委托共享 helper

`_resolve_default_end_date()`（90 行）改为调用 `resolve_signal_date_iso()`，保留原签名和返回值。**现有 7 个测试（`tests/cli/test_input_dates.py`）不受影响** —— 它们 patch `src.cli.input.datetime`，helper 内部也用被 patch 的 `datetime.now()`，行为一致。注释更新说明已委托共享实现。

## 改动 2：`--daily-action` 增加 17:00 感知 + `--end-date` 覆盖

### 2a. `src/screening/offensive/daily_action.py`

`generate_daily_action`（458 行）签名新增 keyword-only 参数 `end_date: str | None = None`（YYYYMMDD，兼容带 `-`）。

`full_market` 分支（508 行）逻辑改为：

```python
if end_date:
    # 显式覆盖：跳过 price_cache 探测，直接用指定日期
    trade_date = _compact_trade_date(end_date)
    regime = _regime_from_history(trade_date)  # 新小 helper，从 regime_history.json 读
else:
    trade_date, regime = _resolve_trade_date_and_regime()
```

`_resolve_trade_date_and_regime()`（216 行）增加 17:00 guard：在用 price_cache 的 `latest_date` 之后，新增判断——

```python
# 17:00 guard: 盘前 price_cache 已有当日数据时，回退到昨天作信号日
# (当日资金流 ~17:00 才就绪，盘中数据不完整)
signal_today = resolve_signal_date()  # YYYYMMDD
if latest_date > signal_today:
    # price_cache 比规则计算的信号日还新（极罕见，如手动注入当日），回退
    latest_date = signal_today
elif latest_date == datetime.now().strftime("%Y%m%d") and latest_date != signal_today:
    # 当日 <17:00 且 cache 含当日 → 用昨天的信号日
    latest_date = signal_today
```

关键：**不破坏 `tests/offensive/test_daily_action.py:573` 的 `test_resolve_trade_date_normalizes_mixed_price_cache_date_formats`**。该测试 cache 最新日是 `20260708`、断言 `trade_date == "20260708"`。只要测试运行当天的 `resolve_signal_date()` 返回值 ≥ `20260708`（即不是"今天=20260708 且 <17:00"），guard 不触发。为彻底消除对运行日期的敏感性，**该测试加 freeze（patch `resolve_signal_date` 返回固定值 `20260709`）**，使断言确定。

### 2b. `src/cli/dispatcher.py` `_resolve_daily_action`（927 行）

读 `--end-date`（复用既有 `_get_kv(...) or _next_arg(...)` 习惯，两种形式都支持），规范化成 YYYYMMDD，传给 `generate_daily_action(tracker=tracker, end_date=end_date)`。`tracker.last_action_trade_date` 已在 511/537 行被设置，dispatcher 945 行读取不变。

**`--end-date` 与 `_missed_entry_window_reason` 的交互**：强制一个**已过买入窗口**的旧日期（如今天 0709 强制 `--end-date 2026-07-07`，对应买入日 0708 < 今天）会触发 missed-window 保护、不出新 BUY。这是**正确行为**（过期信号本就不该下单），不需绕过。若用户想回放历史，可借此验证。

## 改动 3：两个 shell 脚本的 backfill pass 对齐 `--auto` 的日期

### 3a. `scripts/run_daily_auto.sh:86-94`

```bash
"$PYTHON" -c "
from src.utils.date_utils import resolve_signal_date
from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.recommendation_tracker import update_tracking_history
today = resolve_signal_date()
n = update_tracking_history(reports_dir=resolve_report_dir(), trade_date=today)
print(f'[daily_auto] backfill pass updated {n} records')
"
```

（去掉 `from datetime import datetime` + 第 92 行裸 `datetime.now()`）

### 3b. `scripts/run_daily_auto_launcher.sh:82-88`

heredoc 内同理：`from src.utils.date_utils import resolve_signal_date` + `trade_date=resolve_signal_date()`。

**效果**：backfill 的 `trade_date` 与 `--auto` 写报告用的日期（都走 17:00 规则）一致 → `update_tracking_history` Phase 1 能找到正确的 `auto_screening_<date>.json`，不再孤立当日推荐。

## 改动 4：清理残留报告

`auto_screening_20260709.json` 是旧逻辑（17:00 引入前）凌晨跑出的产物，price_cache 只有到 0708。**删除它**。之后 `--daily-action` 的 staleness 检查：`latest_report_date`(0708) ≤ `trade_date`(0708) → 不触发，恢复正常。

（只删这一个文件；其余 0708 及更早报告保留。）

## 测试计划

1. **新增 `tests/offensive/test_daily_action.py` 用例**（沿用该文件 monkeypatch 习惯）：
   - `test_resolve_trade_date_applies_1700_guard`：cache 最新日 = 今天、patch `resolve_signal_date` 返回昨天 → `trade_date` = 昨天。
   - `test_generate_daily_action_end_date_override`：传 `end_date="20260706"` → `tracker.last_action_trade_date == "20260706"`，跳过 cache 探测。
   - 冻结现有 `test_resolve_trade_date_normalizes_mixed_price_cache_date_formats`（patch `resolve_signal_date`）消除日期敏感性。

2. **新增 `tests/cli/test_input_dates.py` 用例**：`_resolve_default_end_date` 委托 helper 后仍返回 `YYYY-MM-DD`（回归，确保 delegate 不破契约）。

3. **新增 `tests/utils/test_date_utils.py`**：`resolve_signal_date` / `resolve_signal_date_iso` 的 17:00 边界（<17→昨、≥17→今、`DATA_READY_HOUR` 覆盖、非法回退）。

4. **dispatcher 测试**：`tests/test_cli_dispatcher.py:244` 的 fake handler 用 `**_kwargs` 吞参，新增 `end_date=` 不破现有测试；加一例 `--daily-action --end-date=2026-07-06` 的 argv 解析。

5. **运行验证**（实现后）：
   - `uv run pytest tests/offensive/ tests/cli/test_input_dates.py tests/utils/test_date_utils.py tests/test_cli_dispatcher.py -v`
   - `uv run python src/main.py --daily-action`（确认不再触发 staleness、标题日期 = 0708）。

## 验证口径

- "完成"= 上述测试全绿 + `--daily-action` 实跑无 staleness 告警 + 标题信号日 = 0708。
- 不动 `--auto` 主路径（已正确），不动 `daily_accumulate.py`（已用 `_resolve_default_end_date`，可后续统一改为 helper，本次不强制）。
- 不引入 freezegun（项目测试用 `unittest.mock.patch` 模式，保持一致）。

## 文件清单

| 文件 | 改动 |
|---|---|
| `src/utils/date_utils.py` | 新增 `resolve_signal_date` + `resolve_signal_date_iso` |
| `src/cli/input.py` | `_resolve_default_end_date` 委托 helper |
| `src/screening/offensive/daily_action.py` | `generate_daily_action` 加 `end_date` 参数；`_resolve_trade_date_and_regime` 加 17:00 guard |
| `src/cli/dispatcher.py` | `_resolve_daily_action` 读 `--end-date` 传入 |
| `scripts/run_daily_auto.sh` | backfill pass 用 `resolve_signal_date()` |
| `scripts/run_daily_auto_launcher.sh` | backfill pass 用 `resolve_signal_date()` |
| `data/reports/auto_screening_20260709.json` | 删除（残留） |
| `tests/utils/test_date_utils.py` | 新增 |
| `tests/offensive/test_daily_action.py` | 加 3 例 + 冻结 1 例 |
| `tests/cli/test_input_dates.py` | 加 delegate 回归 |
| `tests/test_cli_dispatcher.py` | 加 `--end-date` 解析例 |