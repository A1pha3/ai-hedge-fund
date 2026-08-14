# daily-action / BTST 链路运维手册

**适用范围**：每日 BTST 选股→计划→模拟台账（v2 ledger）链路的运行、监控与故障恢复。
**生效日期**：2026-08-14（regime gate 接线 + 台账重置开新档之后）。

## 链路总览

```
launchd 工作日 21:30 (com.a1pha3.ai-hedge-fund.daily-auto)
  └─ ~/.local/bin/run_daily_auto_launcher.sh   ← boot 卷副本 (NS-5 沙箱约束)
       Step 1  src/main.py --auto              数据刷新 + 发布 readiness manifest/snapshot
       Step 2  backfill (tracking_history)     非致命
       Step 3  flywheel 健康检查               非致命
       Step 4  regime winrates 重算            非致命
       Step 5  src/main.py --daily-action      BTST 扫描→次日计划→台账生命周期 (2026-08-14 起接入)
```

- **信号日规则**：17:00（Asia/Shanghai）后当日数据视为就绪；21:30 运行时信号日=当日（交易日）。
- **计划→入场**：当晚创建的计划按**次日开盘价**成交（T+1 open），T+9 标记 / T+10 强制时间退出；无止损执行（2026-08-14 联合网格数据否决，gate 替代止损）。
- **节假日**：信号解析回落到上一交易日，计划幂等去重（`create_plan_if_absent`），重复运行安全。

## 监控

| 检查 | 位置 | 正常状态 |
|---|---|---|
| 上次退出码 | `launchctl list \| grep a1pha3` 首列 | `0`；`11`=--auto 失败，`12`=--daily-action 失败 |
| 运行日志 | `~/Library/Logs/ai-hedge-fund/daily_auto.out.log`（launchd）<br>`logs/auto_cron_YYYYMMDD.log`（交互运行） | 末尾 `--daily-action OK` + `done` |
| 当日计划 | 每晚日志尾部渲染 / 手动重跑 `--daily-action` | 新计划数 + 阻断原因可读 |
| 数据飞轮 | 日志中 `flywheel: {"status": "healthy" ...}` | `stale: false` |
| regime 标签 | `data/reports/regime_winrates_recomputed_<date>.json` | 当日日期 |

## fail-closed 行为（看到 0 计划时先查这里）

链路在任何数据不可信时**宁可不计划也不瞎计划**：

| 阻断原因 | 含义 | 处置 |
|---|---|---|
| `入场窗口已过` | 运行时刻已过入场日 09:30 | 正常守卫；当晚 21:30 运行不会触发 |
| readiness 阻断 | manifest 缺失/过期/校验失败（含 regime 标签非 canonical） | 先手动 `src/main.py --auto` 刷新，再 `--daily-action` |
| `regime_gate_halt` | 信号日 regime ∈ {crisis, risk_off}，不开新仓 | **预期行为**，无需处置；被挡候选进面板对照组 |
| `触发强度不足` | trigger_strength < 0.50 gate | 预期行为 |
| 行业/资金流条件 miss | 条件 2/3 数据缺失即 miss（2026-08-14 起严格化） | 单日数据事故会表现为当日 0 信号，次日自愈；连续多日 → 查 tushare 缓存 |

## 手动操作

```bash
# 手动跑完整夜间链（交互式，绕开 launchd 沙箱）
scripts/run_daily_auto.sh

# 只补跑 daily-action（--auto 已成功、快照已在）
.venv/bin/python src/main.py --daily-action

# 补历史日期（必须是开市日）
scripts/run_daily_auto.sh --trade-date 20260814
```

## launcher 更新流程

launchd 只认 boot 卷副本（/Volumes 路径会被沙箱拦截）。改完 repo 里的
`scripts/run_daily_auto_launcher.sh` 后必须安装：

```bash
cp scripts/run_daily_auto_launcher.sh ~/.local/bin/run_daily_auto_launcher.sh
diff scripts/run_daily_auto_launcher.sh ~/.local/bin/run_daily_auto_launcher.sh   # 须无输出
```

## 已知残留风险（2026-08-14 基线）

1. **2022/2024 跨期未验证**：fund_flow 缓存只覆盖 2025-07+，regime gate 在熊市段（2022）
   的效果只有先验支持（灾难集中 crisis/risk_off），无实证。数据回填后重跑
   `scripts/run_regime_gate_cross_period_court.py` 验证。
2. **资金流条件 2 留待 owner 决策**：A/B 显示微弱正向不显著（被挡组 T+10 +0.78% vs
   通过组 +1.26%，CI 重叠），删除与否是真实取舍。重跑 `scripts/run_gate_cond_ab.py`。
3. **样本外面板仍小**：gate 接线后真实前向样本需时间累积；面板（被挡候选对照组）
   随每日运行自动增长。
4. **2026-08-14 台账重置**：`data/paper_trading_v2/archive/ledger-reset-20260814.sqlite3`
   为旧档，新档从 gate 语义下干净累积——新旧档 P&L 不可直接拼接比较。
5. **trend/MR 降权研究已撤销**（`13d7d9ec`，spec RESEARCH_RECONSTRUCTION_REJECTED）：
   审计口径与生产契约不一致，**禁止**再按该审计结果改 `DEFAULT_STRATEGY_WEIGHTS`。
