## 目标

把 `--daily-action` 的「术语说明」(6 行) 和「执行规则」(5 行) 移到 `--verbose` flag 后面。默认输出精简，跑了一周以上的 operator 不再被每天重复的 11 行噪音干扰。

**保留在默认输出的**：持仓、候选、BUY 计划、风控状态、setup 启用/暂停 —— 这些都是每次跑的决策信息。

## 改动清单（3 个文件，约 30 行净改动）

### 1. `src/screening/offensive/daily_action.py`

**(a) 给 `render_daily_action` 加 `*, explain: bool = False` 参数**（L927-933 签名行）

当前签名已有 `*, closed_positions=...`，在它后面加 `explain: bool = False`。两个 call site（dispatcher.py:952, 965）都是 3 positional，不受影响。

**(b) 用 `explain` gate 术语说明块（L1086-1096）**

```python
if explain:
    lines.append(f"  {Fore.WHITE}术语说明:{Style.RESET_ALL}")
    lines.append(...)  # 6 行原样保留
    # degraded 披露也一起进 explain
```

**(c) 用 `explain` gate 执行规则块（L1098-1103）**

```python
if explain:
    lines.append(f"\n  {Fore.WHITE}执行规则 (按规则执行):{Style.RESET_ALL}")
    lines.append(...)  # 5 行原样保留
```

**(d) journal note（L1106）保留在默认输出**

「已写入 paper journal」是闭环确认，每次都该看到。

**(e) 更新 L1061 的 stale comment**

当前注释「术语完整版见 BUY 路径末尾」→ 改为「术语完整版用 --verbose 查看」。

### 2. `src/cli/dispatcher.py`

**(a) `_resolve_daily_action`（L927-966）解析 `--verbose` flag**

用现有 `_get_kv` / `_next_arg` helper（dispatcher.py:50/58，已支持 `--flag=value` 和 `--flag value` 两种形式）：

```python
verbose = "--verbose" in argv  # bool flag, 无值
```

**(b) 两个 call site 传参（L952, L965）**

```python
print(render_daily_action(actions, trade_date, tracker, explain=verbose))
```

### 3. `tests/offensive/test_daily_action.py`

**(a) `test_render_daily_action_explains_stops_prior_and_rule_execution`（L1292, call at L1317）**

加 `explain=True`：
```python
out = da.render_daily_action(actions, "20260708", tracker, explain=True)
```

这个 test 本来就是验证术语/规则块的存在，语义上就该用 explain=True。

**(b) `test_render_daily_action_does_not_claim_stop_loss_changes_paper_pnl`（L1331, call at L1357）**

同样加 `explain=True`（它断言「止损触发只做披露」「paper P&L 按 T+N 收盘回填」都在术语说明块里）。

**(c) 加一个新 test 验证默认输出不含术语/规则**

```python
def test_render_daily_action_hides_terminology_without_verbose():
    """默认输出不含术语说明/执行规则; --verbose 才展开."""
    # ... setup actions ...
    out = render_daily_action(actions, "20260708", tracker)  # 默认 explain=False
    assert "术语说明" not in out
    assert "执行规则" not in out
    out_verbose = render_daily_action(actions, "20260708", tracker, explain=True)
    assert "术语说明" in out_verbose
    assert "执行规则" in out_verbose
```

## 验证

```bash
uv run pytest tests/offensive/test_daily_action.py -v
uv run pytest tests/test_cli_dispatcher.py -v
uv run python src/main.py --daily-action           # 确认默认不含术语/规则
uv run python src/main.py --daily-action --verbose # 确认 --verbose 展开
```

## 不动的东西

- P&L 口径、setup 逻辑、Kelly 计算、paper journal 真值 —— 全部不动
- 持仓、候选、BUY 计划、风控状态、setup 启用/暂停 —— 保留在默认输出
- `--explain` 顶级命令 —— 完全不碰（用 `--verbose` 避免冲突）