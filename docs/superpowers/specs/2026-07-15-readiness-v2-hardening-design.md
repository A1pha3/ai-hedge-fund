# Auto / Daily Action Readiness v2 修复设计

日期：2026-07-15  
状态：已获用户口头确认，待文档复核  
修复依据：`2026-07-14-auto-daily-readiness-separation.md` 的对抗审查结果

## 1. 目标

用一条可重算、可审计、失败关闭的证据链完成以下闭环：

```text
统一信号交易日
    → 一次刷新并冻结结果
    → Daily Action readiness manifest v2
    → 重算并验证 PIT snapshot
    → setup 检测
    → 携带结构化来源的候选
    → service 二次准入
    → verified ledger provenance
```

同时修复 Auto 评分证据的守恒与门控，使 Auto canonical 只由实际消费的 required scoring evidence 决定；optional evidence 只能告警和关闭对应增强。

## 2. 不变约束

- 不修改 BTST、Kelly、止损、排序阈值或持有期等策略参数。
- OversoldBounce 继续默认关闭，只服从现有显式环境开关。
- 单票上限继续强制为 10%；没有 repository-owned regime 授权证据时不得恢复 12%。
- 不修改 `data/paper_trading_backtest/`、旧回测结果或历史报告。
- Auto 300 与 Daily Action 全市场 universe 保持独立，不恢复 membership 耦合。
- 旧 readiness schema、测试清单、缺失指纹或不可重算的清单保留只读，但一律没有交易授权。

## 3. 设计选择

采用“单一可信结果对象”而不是继续修补三条并行路径。

拒绝的替代方案：

1. **在现有路径逐项加条件**：`main.py` 仍会从目录重建状态，snapshot 仍会重新解释文件，service 仍会使用第三套准入语义，长期必然再次漂移。
2. **重写整个选股系统**：会扩大策略回归面，违反本次只修工程可信边界的约束。

## 4. 统一信号交易日

建立一个严格的 repository-owned resolver，Auto 与 Daily Action 生产入口必须调用同一接口：

- 输入：北京时间、权威开市日集合、可选显式 override。
- 17:00 前使用最近一个已完成交易日；17:00 后只有当日属于权威开市日时才能使用当日。
- override 必须属于权威开市日；周末、节假日和超出日历覆盖范围全部失败关闭。
- 不允许从 `price_cache` 最新文件名或 weekday approximation 猜测交易日。
- resolver 失败不妨碍 Daily Action 推进已有持仓生命周期，但阻止新计划。

## 5. Auto 评分证据

### 5.1 FeatureEvidence 自验证

`FeatureEvidence` 构造时执行完整守恒验证：

- 所有计数为非负整数且拒绝 bool。
- `0 <= nonempty <= usable <= observed <= requested <= eligible`。
- `success` 要求 `requested == observed == usable`、`consumption_failed_count == 0`、`stale_count == 0`。
- `partial` 必须是严格子集或存在明确消费失败。
- required success 必须有 requested / observed / usable 三个非空且相等的 ticker-set fingerprint、非空 `input_fingerprint` 和合法 `as_of_max`。
- required price/financial evidence 必须满足策略登记的最小历史行数。

### 5.2 生产与消费证据

- 每个 requested ticker 保存逐票 provider outcome，不只保存汇总数。
- timeout 后所有未完成 future 转为显式 failed outcome；executor 不得在超时后无限等待。
- company news 或 insider trade 任一必需子源失败时，`event_inputs` 保持 partial。
- optional snapshot 的“文件不存在/损坏”和“权威观察为空”必须是不同状态；只有后者能成为合法空 success。
- `build_quality_summary()` 接受实际逐票 score outputs，验证 required score component 存在且为有限数值。
- provider manifest 和质量证据使用现有原子 JSON writer。

### 5.3 Auto canonical

`assess_auto_quality()` 是 Auto canonical 的唯一质量门控。删除旧 `trade_ready`、Daily Action cache stats、兼容 `optional_features` 对 Auto 发布状态的二次影响。

## 6. FrozenRefreshResult

`refresh_daily_action_caches()` 直接返回不可变的 `DailyActionRefreshResult`：

- 一份日线批次；
- 一份 suspension tri-state 快照；
- 一次冻结并排序的 universe；
- 每只股票互斥的 price / fund-flow outcome；
- 每类结果的守恒统计；
- price、fund-flow、行业和安全状态的规范化 PIT 指纹。

冻结 universe 后，目录新增/删除文件不得改变本次结果。`max_tickers` 之外的股票保留在 universe 中并明确记录 `not_attempted`。provider 失败不能等价为“没有停牌”。

`main.py` 只消费该结果，不再重新 glob 缓存、重新读取行数或自行推断 current。

## 7. Readiness Manifest v2

### 7.1 内容

manifest v2 至少包含：

- schema/domain/run/trade-date identity；
- 排序后的完整 universe 与可重算 fingerprint；
- frozen refresh input fingerprint；
- regime、industry mapping/day-pct、security/ST、suspension 证据及指纹；
- 已知 board rule、normalization、setup requirements、signal-session policy 版本；
- 每 ticker / setup 的 `enabled`、`scannable`、`plan_eligible`、`degraded`、原因和 `consumed_fingerprint`；
- canonical content fingerprint。

### 7.2 严格反序列化

- 使用严格类型判断，禁止 `bool("false")` 一类真值转换。
- universe、ticker readiness key 集合必须完全一致且 fingerprint 可重算。
- 只接受已知 schema 和 policy 版本。
- `plan_eligible` 必须蕴含 enabled、scannable、非 degraded 和完整 consumed fingerprint。
- run ID、input fingerprint、shared evidence fingerprint 不能为空。
- malformed UTF-8、非 object JSON、未知字段类型和能力不变量冲突全部失败关闭。

### 7.3 发布

- 只有完整验证后的 healthy manifest 才能原子替换 canonical。
- 失败、降级或原子替换异常只写 `daily_action_readiness_attempt_<date>_<run_id>.json`。
- 旧 canonical 保持不变。

## 8. Verified PIT Snapshot

loader 只接收 manifest v2，使用安全文件读取并重算所有 `date <= signal_date` 投影：

- price；
- fund flow；
- industry mapping 和目标日行业涨跌；
- ST / listed / suspension 状态；
- regime 和版本化策略证据。

未来日期追加不改变历史 fingerprint；任何历史行修改、删除或替换都会使相关 scope 阻断。snapshot ID 由已验证 canonical 内容和实际消费指纹共同计算。

snapshot 内部使用冻结的规范化 record tuple；只有 setup adapter 在调用 detector 前生成私有 DataFrame。不得向外公开可变 DataFrame，也不得在验证后重新打开缓存或走 legacy fallback。

安全读取必须拒绝最终路径和祖先路径中的 symlink，并在读取前后校验路径所指 inode/元数据没有变化。

## 9. Scanner、Service 与 Ledger

### 9.1 结构化来源

`DailyActionScan` 和 `PlanCandidate` 必须携带：

- signal date；
- snapshot ID；
- ticker；
- setup 名称和版本；
- setup consumed fingerprint；
- detector degraded 状态；
- 目标仓位和排序优先级。

来源字段不得只存在于 reasoning 字符串。

### 9.2 双层准入

scanner 在检测前过滤 manifest `plan_eligible=false`，在检测后再次过滤 `result.degraded=true`。两者均可进入诊断显示，但不得成为 actionable candidate。

service 重新验证 candidate 的日期、ticker、setup、snapshot ID、consumed fingerprint、manifest capability 和 detector degraded 状态。任一不匹配都阻断。验证通过后 ledger 保存 verified provenance；snapshot 路径不得退化为 `legacy_unverified`。

### 9.3 生命周期优先

Daily Action 控制流固定为：

1. 解析可用的运行日期上下文；
2. 打开 ledger；
3. settle due entries/exits、估值、更新 open positions；
4. 尝试加载 readiness/snapshot；
5. 扫描并创建新计划，或只记录 new-entry blocker；
6. 渲染完整生命周期结果。

readiness、scanner 或安全读取异常都不能跳过第 3 步。

## 10. 输出

- Auto 和 Daily Action readiness 分成两个独立结论。
- 默认中文输出显示状态、关键计数、影响和下一步，不暴露内部 reason code。
- `--verbose` 保留原始 blocker、fingerprint 和来源信息。
- “无信号”“只有残缺诊断 setup”“readiness 阻断”必须明确区分。
- `regime_authorization_evidence_unavailable` 作为可理解的 10% 降级说明显示，不伪装成交易失败。

## 11. 测试隔离与验收

所有测试使用 `tmp_path` 或显式注入的 reports/data/ledger 路径，禁止写工作区真实 `data/reports`。

每个审计反例按 TDD 执行：先确认旧实现失败，再实现并确认通过。必须覆盖：

- Auto count/fingerprint/time/score-output 守恒；
- required event partial；
- optional missing 与 observed-empty；
- refresh timeout、单批次、suspension tri-state、not-attempted；
- refresh 失败只写 attempt；
- manifest 字符串布尔、伪造 identity、未知 policy；
- 历史价格/资金流/行业篡改与未来追加；
- ancestor symlink、inode replacement、invalid UTF-8、非 object JSON；
- ST/行业缺失与 detector degraded display-only；
- candidate snapshot/setup fingerprint mismatch；
- 17:00、周末 override、Friday→Monday；
- readiness 缺失时生命周期继续；
- 重复运行不重复创建 plan/event；
- 真实 Auto orchestration → manifest → loader → scanner → service E2E。

最终验证按顺序执行：定向反例、完整 scoped pytest、compileall、diff check、隔离命令烟测。只有全部确定性测试通过后，才允许在用户确认的数据目录上运行网络支持的真实 `--auto`。

## 12. 迁移

- schema v2 上线后，现有 v1 canonical 会被明确报告为“旧版清单，无交易授权”。
- 用户在收盘后重新运行 `--auto` 生成首个 v2 canonical。
- 不删除或重写旧 canonical、attempt、回测和 ledger；只拒绝用它们授权新的买入计划。
