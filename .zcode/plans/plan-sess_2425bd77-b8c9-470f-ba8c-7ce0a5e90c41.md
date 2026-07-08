# 修正 regime 加仓（按 setup 区分）+ 暂停 OversoldBounce

## 第一性原理依据（真实回测数据验证，非 Phase 0 假设）

我第二轮基于不可复现的 Phase 0 报告实现了**统一** regime 加仓。但用 `data/paper_trading_backtest/`（192 笔真实成交，2026-01→07）验证后发现：

```
BTST 按 regime (2026 实测, n=133):
  crisis:    winrate=76%  E[r]=+16.93%  ✅ 加仓有数据支持
  risk_off:  winrate=78%  E[r]=+8.87%   ✅
  normal:    winrate=66%  E[r]=+6.29%   ✅ 本来就强

OversoldBounce 按 regime (2026 实测, n=59):
  crisis:    winrate=48%  E[r]=-1.15%   ❌ 亏钱! 我却给它加仓 1.2×
  risk_off:  winrate=100% E[r]=+13.11%  (n=3, 太少不可信)
  normal:    winrate=51%  E[r]=+0.15%
  整体:      E[r]=+0.34% 几乎无效
```

**结论**：统一加仓对 OversoldBounce 有害。需按 setup 区分，且暂停 OversoldBounce（实测 E[r]≈0）。

⚠️ 统计诚实：OversoldBounce crisis 仅 21 笔、整体仅 6 个月，可能有样本期偏差。因此"暂停"用 env 开关实现（默认关但可开回），不删除代码/数据。

---

## 改动 1：regime 加仓按 setup 区分（`daily_action.py`）

### 重构 `_regime_size_factor` → `_regime_size_factor(regime, setup_name)`

把统一映射改成按 setup 的二级 dict：

```python
# 按 setup 区分的 countercyclical 加仓系数 (2026 回测数据验证).
# BTST 在 crisis/risk_off 表现强 (E[r]=+16.93%/+8.87%) → 加仓捕获.
# OversoldBounce 在 crisis 实测亏钱 (E[r]=-1.15%) → 不加仓, 避免放大无效 setup.
_REGIME_SIZE_FACTORS_BY_SETUP = {
    "btst_breakout": {"crisis": 1.2, "risk_off": 1.1, "normal": 1.0},
    "oversold_bounce": {"crisis": 1.0, "risk_off": 1.0, "normal": 1.0},  # 实测无效, 不加仓
}
```

`_regime_size_factor(regime, setup_name)`:
- 查 `_REGIME_SIZE_FACTORS_BY_SETUP.get(setup_name, {})` 再 `.get(regime, 1.0)`
- env `DAILY_ACTION_REGIME_SIZING=false` 仍全局关闭（退回 1.0）
- 未知 setup / 未知 regime → 1.0（保守）

### 更新 Kelly 调用点（`:519`）
```python
regime_factor = _regime_size_factor(regime, setup_name)  # 加 setup_name 参数
```
两处 reasoning 字符串（`:551`, `:583`）已含 `regime={regime}×{factor}`，自动反映新值，无需改。

---

## 改动 2：暂停 OversoldBounce（`daily_action.py`）

### 用 env 开关，不删代码（可逆，符合现有惯例）
在 `_VERIFIED_SETUPS` 构建循环（`:457-463`）加暂停过滤：
```python
_DISABLED_SETUPS = _env_setup_disable_list()  # 解析 DAILY_ACTION_DISABLED_SETUPS
for name, cls, horizon in _VERIFIED_SETUPS:
    if name in _DISABLED_SETUPS:
        logger.info("setup %s 已通过 DAILY_ACTION_DISABLED_SETUPS 暂停, 跳过", name)
        continue
    ...
```

新增 helper `_env_setup_disable_list() -> set[str]`：解析 `DAILY_ACTION_DISABLED_SETUPS`（逗号分隔，如 `"oversold_bounce"`）。

### 默认值设计（关键决策）
在 `daily_action.py` 模块顶部定义 `_DEFAULT_DISABLED_SETUPS = {"oversold_bounce"}`，helper 合并 env + 默认：
```python
def _env_setup_disable_list() -> set[str]:
    disabled = set(_DEFAULT_DISABLED_SETUPS)  # 默认暂停 oversold_bounce
    raw = os.environ.get("DAILY_ACTION_DISABLED_SETUPS", "")
    # env 可追加禁用, 也可用 "none" 清空默认
    if raw.strip().lower() == "none":
        return set()
    disabled.update(s.strip() for s in raw.split(",") if s.strip())
    return disabled
```
- **默认暂停 OversoldBounce**（基于 2026 实测 E[r]≈0）
- `DAILY_ACTION_DISABLED_SETUPS=none` 可恢复全部 setup（让用户在补全历史数据重跑后能轻易开回）
- 可追加禁用其他 setup

---

## 改动 3：测试更新（`tests/offensive/test_daily_action.py`）

### 需修改的现有测试：
1. **`test_verified_setups_includes_both_btst_and_oversold`**（`:1034`）：`_VERIFIED_SETUPS` 常量不变（仍含两个），改断言只检查 BTST 在内（OversoldBounce 暂停是运行时过滤，不是改常量）。或改为测 `_VERIFIED_SETUPS` 常量 + 单独测默认禁用列表。

### 新增测试：
2. **`test_regime_factor_btst_crisis_increases`**：BTST + crisis → 1.2×（数据支持）
3. **`test_regime_factor_oversold_crisis_no_increase`**：OversoldBounce + crisis → 1.0×（修正：不再加仓）
4. **`test_oversold_bounce_disabled_by_default`**：默认配置下 OversoldBounce 不进 setup_configs（不产生 BUY）
5. **`test_oversold_bounce_reenabled_via_env_none`**：`DAILY_ACTION_DISABLED_SETUPS=none` → OversoldBounce 恢复
6. **`test_disabled_setup_appended_via_env`**：`DAILY_ACTION_DISABLED_SETUPS=btst_breakout` → 追加禁用 BTST

### 第二轮已有的 regime 测试（`:1098-1148`）需调整：
- `_run_daily_action_under_regime` helper 用 `fake_setup`，不受按 setup 区分影响（fake_setup 不在 dict → 默认 1.0）。但这些测试断言"crisis → 0.12"。需改为用 `btst_breakout` 验证加仓，或保留 fake_setup 测"未知 setup 不加仓"。
- 决策：把现有的 crisis 加仓测试改用 `btst_breakout`（真实有加仓的 setup），fake_setup 测试改为"未知 setup 不加仓"。

---

## 不改动的地方
- ❌ 不删除 OversoldBounce 代码/known_distribution（只是运行时不启用，保留可逆性）
- ❌ 不改 `_VERIFIED_SETUPS` 常量（暂停是运行时过滤，不是改注册表）
- ❌ 不动止损执行（仍保留为后续选项）
- ❌ 不动 trailing stop（仍需历史数据补全后回测验证）
- ❌ 不动 `known_distributions.py` 的数字（本地无法重算，保持原值）

## 验证步骤
1. `uv run pytest tests/offensive/test_daily_action.py -v` — 新测试 + 修改的测试通过
2. `uv run pytest tests/offensive/ -v` — 全套件无回归
3. 手动验证：`DAILY_ACTION_DISABLED_SETUPS` 默认 → OversoldBounce 不出 BUY；`=none` → 恢复
4. 回测一致性：修正后，crisis regime 下只有 BTST 加仓（与 2026 实测 BTST crisis 强、OversoldBounce crisis 弱一致）

## 风险评估
- **regime 按 setup 区分**：风险低。直接基于真实回测数据，比统一加仓更准确。硬上限/组合上限不变。
- **暂停 OversoldBounce**：风险低且可逆。默认暂停基于 6 个月实测，但 `=none` 一键恢复。若后续补全历史数据重跑证明 OversoldBounce 有效，改默认值即可。
- **统计诚实**：OversoldBounce crisis n=21 偏小，但整体 E[r]≈0（n=59）更稳健。暂停是保守选择，不删除是保留可逆性。