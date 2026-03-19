# W3 Data Readiness Check

## 1. 结论

截至 `2026-03-20`，W3 还不具备直接起跑条件。

原因不是 W2 口径未收口，而是本地用于判定扩窗可执行性的日级数据覆盖明显不足。

当前检查结果显示：

1. `data/stock/daliy/` 目录下当前仅看到 `daily_gainers_20260303_gt5p0_20260303_214747.md`。
2. 未发现覆盖 `2026-03-14` 之后连续交易日的本地日级数据文件集合。
3. 在这种状态下，无法把 `W3` 解释成“与 W0/W1/W2 同口径、可稳定复跑、可生成 summary 的非重叠 holdout 窗口”。

因此，当前最严格的处理方式应是：

1. 不直接启动 W3 live run。
2. 先把 W3 状态记为 `data_not_ready`。
3. 后续只有在本地数据覆盖完成后，才恢复 W3 执行判断。

## 2. 本次检查方法

本次不是重新扫描所有 reports，而是按更长窗口计划的最小执行清单，优先检查本地数据可执行性。

执行观察：

1. `data/reports/**/*w3*` 未发现现成 W3 产物。
2. `data/stock/` 下仅存在 `daliy/` 目录。
3. `data/stock/daliy/` 当前仅列出一份 `20260303` 相关文件，没有形成 `2026-03-13` 之后的连续数据覆盖证据。

## 3. 对 W3 的直接影响

这次检查带来的不是策略结论，而是执行门槛结论：

1. W3 当前不能被视为“待运行”，而应视为“等待数据就绪”。
2. 因为缺的不是 runtime 资源，而是窗口可复验所需的数据覆盖，所以继续硬跑只会产出低可比性的 probe。
3. 按现有研究纪律，`data_not_ready` 比生成一份不可比 W3 probe 更有价值。

## 4. 当前建议

在数据补齐前，后续工作优先顺序建议改成：

1. 保持 W2 contaminated 与 clean 双证据口径冻结。
2. 若要继续推进严格性，优先设计 `single-provider-only session` 独立验证线，而不是伪启动 W3。
3. 等本地数据覆盖到 `2026-03-14` 之后连续交易日，再重新执行 W3 readiness check。

## 5. 相关文档

1. [longer-window-validation-plan-20260318.md](./longer-window-validation-plan-20260318.md)
2. [w2_minimax_m2_7_branch_decision_gate_20260320.md](./w2_minimax_m2_7_branch_decision_gate_20260320.md)
3. [validation-scoreboard-20260318.md](./validation-scoreboard-20260318.md)
