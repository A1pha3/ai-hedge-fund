# scripts/archive/2026Q2_baseline/ — 2026 Q2 归档脚本

> ⚠️ **本目录是历史快照, 不再维护**。
> 此处脚本仅用于复盘 2026-04-05 / 2026-05-15 两次 BTST 边界与 baseline 冻结决策。
> 日常请改用 `analyze_btst_5d_15pct_objective_monitor.py` 与 `run_btst_top3_experiments.py`。

## 何时移入

- 原位置: `scripts/_p0_baseline_stats.py` 与 `scripts/analyze_btst_5d_15pct_*.py`
  共 19 个文件
- 移入时间: 2026-06-06 (策略研究团队第二轮审计后)
- 移入原因: Feature Proposal 3.2 — 这些是 4-5 月期间 BTST 5d/15pct 边界
  实验的产物, 当前已被 `analyze_btst_5d_15pct_objective_monitor.py` 替代,
  启动时偶尔报 `ModuleNotFoundError` 来自陈旧 `__pycache__` 引用。

## 替代方案

| 归档脚本主题 | 替代脚本 |
|--------------|----------|
| 5d/15pct 边界 quarantine | `analyze_btst_5d_15pct_objective_monitor.py` |
| 5d/15pct 边界 false negative | `analyze_btst_5d_15pct_false_negative_diagnostic_board.py` (主线) |
| 5d/15pct 趋势 gate 网格 | `run_btst_top3_experiments.py` (profile 实验) |
| 5d/15pct OOS 验证 | `validate_btst_early_runner_history.py` (新版) |

## 测试影响

19 个对应的 `tests/scripts/test_analyze_btst_5d_15pct_*.py` 单元测试
**仍然引用原路径** (`scripts/analyze_btst_5d_15pct_*.py`), 因此
本次移入采用**软归档**: 脚本仍保留在 `scripts/` 根目录, 但顶部
加 `# Status: experimental / archived` 标记, 配合本 README 表明"不再维护"。

## 启用真正的物理移入 (Hard Archive)

如确需将脚本物理移入本目录并更新测试路径, 需执行:

```bash
# 1. 移入脚本
git mv scripts/analyze_btst_5d_15pct_*.py scripts/archive/2026Q2_baseline/
git mv scripts/_p0_baseline_stats.py scripts/archive/2026Q2_baseline/

# 2. 更新 19 个测试文件的 import 路径
#    scripts.analyze_btst_5d_15pct_X → scripts.archive.2026Q2_baseline.analyze_btst_5d_15pct_X

# 3. 跑回归确认
uv run pytest tests/scripts/ -v
```

## 归档目录为何存在

`scripts/README.md` 提案 5.6 之前已建立完整的脚本索引。本目录的
存在意义是:

1. **明确边界**: 让 grep `archive/` 的开发者立即知道"这是历史"
2. **避免混淆**: 防止 `analyze_btst_5d_15pct_*.py` 这类相似名字
   让人误以为是当前活跃脚本
3. **未来物理归档的预演**: 准备好目录结构和说明, 真要移入时
   不用再写新文档

---

**最后更新**: 2026-06-06 (策略研究团队第二轮审计)
