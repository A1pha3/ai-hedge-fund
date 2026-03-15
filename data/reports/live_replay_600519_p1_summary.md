## 600519 P1 Live Replay 汇总

本摘要用于快速判断 20260224 和 20260226 两个目标日期是否符合 P1 的最小业务补证预期。

### 20260224 / 600519

- 来源文件：/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/live_replay_600519_20260224_p1.json
- variant：neutral_mean_reversion_guarded_033_no_hard_cliff.timings
- logged：score_final=0.1584，decision=watch，bc_conflict=None
- replay：score_c=-0.0122，score_final=0.2158，decision=watch，bc_conflict=None
- delta：score_c=-0.0079，score_final=0.0574
- cohort：investor=-0.0122，analyst=0.0000，other=0.0000
- 对照基线：旧 replay score_final=0.1979，旧 logged score_final=0.1584
- 验收结论：ideal
- 说明：达到理想验收：已跨过 0.20 watchlist 门槛。

可直接贴入文档的结论：

> 20260224 / 600519 的 live replay 结果为 score_c=-0.0122、score_final=0.2158、decision=watch、bc_conflict=None。相较既有 replay，score_final 变化 0.0574。达到理想验收：已跨过 0.20 watchlist 门槛。

### 20260226 / 600519

- 来源文件：/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports/live_replay_600519_20260226_p1.json
- variant：neutral_mean_reversion_guarded_033_no_hard_cliff.timings
- logged：score_final=0.1580，decision=watch，bc_conflict=None
- replay：score_c=-0.0469，score_final=0.1962，decision=watch，bc_conflict=None
- delta：score_c=-0.0469，score_final=0.0382
- cohort：investor=-0.0469，analyst=0.0000，other=0.0000
- 对照基线：旧 replay score_final=0.0791，旧 logged score_final=0.1580
- 验收结论：ideal
- 说明：达到理想验收：仍保持边缘不过线，没有滑向更激进的 P2 区间。

可直接贴入文档的结论：

> 20260226 / 600519 的 live replay 结果为 score_c=-0.0469、score_final=0.1962、decision=watch、bc_conflict=None。相较既有 replay，score_final 变化 0.0382。达到理想验收：仍保持边缘不过线，没有滑向更激进的 P2 区间。
