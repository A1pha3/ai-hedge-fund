# 分析单只股票

- 运行此命令会生成report ./scripts/run-hedge-fund.sh --ticker 600989 --model MiniMax-M2.5 --start-date 2025-06-01 --analysts-all --show-reasoning 此命令会生成每只股票对应的markdown格式的分析报告, 保存到 /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports 目录下,
- 你仔细分析上面命令生成的报告中的数据是否有错误，如果有错误，你要仔细说明如何修改，并仔细审阅方案两次修改方案是否正确，如果正确，就按方案进行修改，修改完成后，清除缓存，继续执行上面的命令，检查report，验证修改是否正确，如果有错误，继续修改，直到正确。
- 如果报告中有数据没有获取到，详细记录哪些数据没有获取到，并给出最合理的获取数据的方案，如果方案正确可行，就实施。
- 用alpha-loop 迭代上面这个过程10次。

# 批量分析股票数据(一次分析一只股票)
- 运行此命令 uv run  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260302_gt5p0_20260302_182924.md  --model MiniMax-M2.5 --start-date 2025-05-30 --analysts-all  --limit 1 --show-reasoning 
- 此命令会生成每只股票对应的markdown格式的分析报告, 保存到 /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports 目录下, 你仔细分析报告的数据是否有错误，如果有错误，你要仔细说明如何修改，并仔细审阅方案两次修改方案是否正确，如果正确，就按方案进行修改，修改完成后，清除缓存，继续执行上面的命令，检查report，验证修改是否正确，如果有错误，继续修改，直到正确。
- 如果报告中有数据没有获取到，详细记录哪些数据没有获取到，并给出最合理的获取数据的方案，如果方案正确可行，就实施。
- 用alpha-loop 迭代上面这个过程10次。


# 每日批量生成股票分析
- 运行此命令 uv run  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260302_gt5p0_20260302_182924.md --model MiniMax-M2.5 --start-date 2025-05-30 --analysts-all --show-reasoning 
- 此命令会根据输入文件中的股票，产生大量分析报告，每个股票会生成一个md文件，你耐心等待所有结果生成完成，如果程序中间出现错误，导致程序停止运行。你去检查错误原因，如果能修复就修复问题，问题修复后，继续执行上面这个命令分析股票，直到所有股票分析完毕。


# 推理过程

