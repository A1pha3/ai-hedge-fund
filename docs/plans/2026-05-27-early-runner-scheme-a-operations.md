# Early Runner Scheme A 日常运行与切换规范

> 适用范围：`scripts/generate_btst_doc_bundle.py` 已经能够输出含 early-runner 章节的 BTST 文档包，但当前仍处于观察期，需要把日常运行、复盘记录和正式切换条件彻底标准化。

## 这份规范解决什么问题

这份文档只解决三件事：

1. 每天怎么最省力地生成一套可读、可执行、可复盘的 BTST 文档包。
2. 观察期里怎么判断 early-runner 是“当日可用”还是“只能参考”。
3. 什么时候可以把输出目录从 `scheme_a` 切回正式目录。

如果这三件事不写清楚，最容易发生的不是“脚本跑不通”，而是下面这些更隐蔽的问题：

- 文档偶尔能跑通，但每天读法都不一样。
- 旧板回退被误读成当日交集信号。
- 补充观察票慢慢漂成主执行票。
- 正式目录混入试运行产物，后面无法复盘归因。

## 先记住一句话

观察期的目标不是证明 early-runner 很强，而是证明这套系统已经足够稳定、足够省心、足够不容易误导正式决策。

## 输出目录规范

输出目录**必须按 signal_date 归档**，避免出现“目录日期与文件信号日不一致”（例如 `outputs/202605/20260522/` 里却包含 `BTST-20260521.md`）导致复盘与执行误读。

- `next_trade_date` 仍然会写入所有文档头部与 `manifest.json`，用于次日执行对齐。

### 观察期目录（scheme_a）

观察期统一输出到：

```text
outputs/<signal_yyyymm>/<signal_yyyymmdd>_scheme_a/
```

例如（signal_date=20260526 → next_trade_date=20260527）：

```text
outputs/202605/20260526_scheme_a/
```

### 正式目录（非 scheme_a）

观察期通过后，正式目录为：

```text
outputs/<signal_yyyymm>/<signal_yyyymmdd>/
```

### 为什么必须分目录

分目录的意义不是形式化，而是为了同时满足三件事：

1. 观察期产物不覆盖原有正式文档。
2. 你可以直接对比“旧流程文档”和“方案 A 文档”。
3. 一旦规则调整失败，可以快速回看 `scheme_a` 版本，不污染正式归档。

## 每日标准运行链路

### 场景 A：标准收盘后运行

这是默认流程，适用于绝大多数交易日。

#### Step 1：刷新 early-runner 主 artifact

```bash
uv run python scripts/analyze_btst_early_runner_v1.py
```

这一步确认最新 `daily_boards`、ledger 和状态字段是否已刷新。没有这一步，后面所有文档都可能只是拿旧板做装饰。

#### Step 2：生成 early-runner 日表

```bash
uv run python scripts/generate_btst_early_runner_daily_tables.py
```

这一步把聚合 artifact 拆成文档更好消费的三个入口：

- `early_runner_watchlist`
- `early_runner_priority`
- `second_entry_reentry`

#### Step 3：刷新 manifest 与 nightly control tower

```bash
uv run python scripts/generate_reports_manifest.py
uv run python scripts/run_btst_nightly_control_tower.py
```

这一步的作用不是“多跑两个脚本”，而是确保 early-runner 的状态变化在仓库其它视图里也是一致的。后续做复盘时，文档、manifest 和 control tower 才能互相对得上。

#### Step 4：生成方案 A 文档包

```bash
uv run python scripts/generate_btst_doc_bundle.py \
  --signal-date YYYYMMDD \
  --scheme-a \
  --no-refresh-early-runner
```

例如（signal_date=20260526 → next_trade_date=20260527）：

```bash
uv run python scripts/generate_btst_doc_bundle.py \
  --signal-date 20260526 \
  --scheme-a \
  --no-refresh-early-runner
```

> 注：不传 `--output-dir` 时，脚本会用 SSE 交易日历严格推算 `next_trade_date`，但**默认输出目录仍以 `signal_date` 为锚点**（见上方规范），同时落 `manifest.json` 记录两日期与 `calendar_source`。

默认保留 `--no-refresh-early-runner`，因为刷新动作已经在前面单独执行。这样一来，问题更容易定位，连续多日也更稳定。

#### Step 5：登记当天结果

最少记录下面这些字段：

- `signal_date`
- `output_dir`
- `early_runner_status`
- `early_runner_latest_trade_date`
- 交集票
- only early-runner 票
- 是否手工修补
- 收盘复盘结论

### 场景 B：忙碌日快速版

如果当天只想快速拿到核心文档，使用：

```bash
uv run python scripts/generate_btst_doc_bundle.py \
  --signal-date YYYYMMDD \
  --scheme-a \
  --no-refresh-early-runner \
  --core-only
```

这会只保留 5 份核心文档，减少产物数量，但不改变选股分层逻辑。

### 场景 C：阶段评审前的历史回放验证

在做阶段评审或切回正式目录前，额外跑一遍历史回放验证：

```bash
uv run python scripts/validate_btst_early_runner_history.py \
  --month-prefix YYYYMM \
  --output-dir outputs/YYYYMM/validation_scheme_a
```

这一步能快速回答两个关键问题：

1. 本月有多少天是 `exact`，多少天是 `stale_fallback`。
2. 交集票高亮和 only early-runner 补充票到底出现过多少次。

## 文档包的标准读法

### 第 1 份：`BTST-LLM-YYYYMMDD.md`

先看正式执行层、观察层、`Early Runner` 章节、交集票高亮和补充观察结论。它是整套文档里信息最全的一份。

### 第 2 份：`BTST-YYYYMMDD-EXEC-CHECKLIST.md`

次日开盘前只看这份也能完成基本执行。重点是：

- 正式执行顺序
- 正式观察顺序
- 交集优先复审
- early-runner 补充观察

### 第 3 份：`BTST-YYYYMMDD-EARLY-WARNING.md`

这份专门看补充池：

- `Priority`
- `Watchlist`
- `Second Entry / Reentry`
- `Only Early Runner`

### 第 4 份：`BTST-YYYYMMDD.md`

这份更像规则底稿，用来复核正式主线和 early-runner overlay。

### 第 5 份：`YYYYMMDD-两套交易计划通俗说明.md`

这份用来快速复盘“为什么今天这样分层”。

如果时间非常紧，前 3 份就够用。

## 每日检查项

每天跑完后，至少检查下面 8 项。

| 检查项 | 标准 | 说明 |
| --- | --- | --- |
| `early_runner_status` | `exact` / `stale_fallback` / `unavailable` | 先判断能不能用，再判断怎么用 |
| `early_runner_latest_trade_date` | 是否等于 `signal_date` | 判断是否拿到当日板 |
| `BTST-LLM` | 是否出现 `Early Runner 章节` 和 `交集票高亮` | 判断 overlay 是否进入主文档 |
| `EXEC-CHECKLIST` | 是否出现 `交集优先复审` | 判断优先级是否进入执行清单 |
| `EARLY-WARNING` | 是否出现 `Only Early Runner` | 判断补充池是否被单独承接 |
| 文件数量 | 标准版 7 份，快速版 5 份 | 判断能否替代手工整理 |
| 人工修补 | 最好为 `否` | 判断流程是否足够顺手 |
| 备注 | 记录异常原因 | 为阶段评审保留证据 |

## 每日状态判读规则

### 当 `early_runner_status=exact`

当天可以按完整方案 A 使用：

- 交集票进入优先复审层
- only early-runner 票进入补充池
- `second_entry_reentry` 进入回补观察层

### 当 `early_runner_status=stale_fallback`

当天必须保守处理：

- 交集票只能写成历史参考
- only early-runner 票只能当辅助线索
- 不允许因为旧板高亮而提高次日执行优先级

### 当 `early_runner_status=unavailable`

当天完全按正式 BTST 走：

- 不补任何 early-runner 票
- 文档里只记录缺失状态
- 不做“猜测式补票”

这三条一定要守住，否则文档流越完善，误导性反而越强。

## 每日记录模板

观察期内，每天建议维护下面这张表。

| 日期 | signal_date | output_dir | early_runner_status | latest_trade_date | 交集票 | only early-runner 票 | second-entry 票 | 是否手工修补 | 收盘后结论 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-27 | 20260526 | outputs/202605/20260526_scheme_a | stale_fallback | 2026-05-14 | [] | [] | [] | 否 | 仅作历史参考 | 首次方案 A 真实生成 |

这张表的用途不是留档好看，而是给后面的升级判断提供原始证据。

## 每周小结模板

每 `5` 个交易日做一次小结，至少统计：

1. `exact` 天数
2. `stale_fallback` 天数
3. `unavailable` 天数
4. 交集票出现天数
5. only early-runner 票出现天数
6. 手工修补天数
7. 交集票的复盘质量是否优于普通观察票

如果这一步不做，到了阶段评审时就只能凭印象说“最近好像顺了很多”。

## 观察期通过标准

满足下面 6 条，才算观察期通过，可以评估是否切回正式目录：

1. 连续 `10` 到 `15` 个交易日都能稳定生成文档包。
2. 最近连续 `3` 个交易日 `early_runner_status=exact`。
3. 最近连续 `3` 个交易日 `early_runner_latest_trade_date == signal_date`。
4. 至少有 `2` 个交易日出现真正基于当日板的交集票高亮。
5. 文档生成过程不需要人工调整层级、交集描述或目录结构。
6. 交集票开始表现出比普通观察票更高的复审价值，哪怕优势还不大。

第 6 条很重要。切回正式目录不只是说明“系统稳定”，还说明“这套额外信息开始值得保留进正式归档”。

## 为什么必须看连续 3 天

单日 `exact` 很可能只是一次偶然成功。连续 `3` 个交易日成立，才更能说明：

- early-runner 近期日期已经基本跟上；
- 交集票高亮开始来自当日板，而不是旧板回退；
- 切回正式目录后，不太会第二天又退回试运行状态。

## 正式切换动作

观察期通过后，文档命令切换为：

```bash
uv run python scripts/generate_btst_doc_bundle.py \
  --signal-date YYYYMMDD \
  --output-dir outputs/YYYYMM/YYYYMMDD
```

例如：

```bash
uv run python scripts/generate_btst_doc_bundle.py \
  --signal-date 20260526 \
  --output-dir outputs/202605/20260526
```

切换后默认含义是：

- 方案 A 已经不再是临时试跑
- early-runner 已经成为稳定观察层
- 正式归档里不再需要额外说明“这是不是实验产物”

## 观察期不通过时怎么办

如果跑满 `10` 到 `15` 个交易日后仍然有下面这些问题，就不要切回正式目录：

- `stale_fallback` 仍然是常态
- `latest_trade_date` 经常落后多个交易日
- 文档长期没有稳定交集票或补充池内容
- 每天还得手工修文档才能维持可读性

这时只做两件事：

1. 先修 early-runner 刷新与日期链路
2. 继续保持输出目录为 `outputs/<signal_yyyymm>/<signal_yyyymmdd>_scheme_a/`

## 推荐日常节奏

最稳的一套节奏如下：

1. 收盘后先刷新 early-runner artifact
2. 生成 early-runner 日表
3. 刷新 manifest 和 control tower
4. 生成方案 A 文档包到 `scheme_a` 目录
5. 快速检查状态、交集票和补充票
6. 收盘后登记结果
7. 每 `5` 日做一次小结，每 `10` 到 `15` 个交易日做一次阶段评审

## 一句话版本

观察期里，统一把文档生成到 `outputs/<signal_yyyymm>/<signal_yyyymmdd>_scheme_a/`；先确保 daily artifact、daily tables、manifest、control tower 和文档包都稳定，再用连续 `10` 到 `15` 个交易日样本验证 `exact`、交集票高亮和手工修补率。只有当它已经稳定、省心、并开始对优先级判断有正面价值时，才切回正式目录 `outputs/<signal_yyyymm>/<signal_yyyymmdd>/`。
