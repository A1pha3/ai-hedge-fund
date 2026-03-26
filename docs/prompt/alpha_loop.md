# replay artifact test

- 根据这个文档的记录，我们的优化任务已经完成，我想跑一次真实的数据，日期是2023年3月23日至2026年3月26日，然后通过我们改造后的的新replay artifacts，去分析系统是否有问题

# 终极目标

- 我觉得目前的测试和结论已经足够了，不需要再花时间去20日了。我们回归的任务主线，继续优化选股策略和我的产品最终目的：选到优质的好股票，能够让我买了赚钱。这也是所有量化交易系统的终极目标
  
# commit

- 现在有很多修改的文件，分析哪些文件需要提交到git，哪些不需要，将需要提交到git的文件提交，不需要提交的加到.gitignore文件中

# new session

- 现在的会话的context window 快满了，我要开一个新的会话，你写个提示词，能够让我们在新会话中继续完美完成我们的后续任务。
  

# 分析单只股票

- 运行此命令会生成report ./scripts/run-hedge-fund.sh --ticker 601016 --start-date 2025-06-01 --analysts-all --show-reasoning 此命令会生成每只股票对应的markdown格式的分析报告, 保存到 /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports 目录下, 默认模型从 .env 读取。
- 你仔细分析上面命令生成的报告中的数据是否有错误，如果有错误，你要仔细说明如何修改，并仔细审阅方案两次修改方案是否正确，如果正确，就按方案进行修改，修改完成后，清除缓存，继续执行上面的命令，检查report，验证修改是否正确，如果有错误，继续修改，直到正确。
- 如果报告中有数据没有获取到，详细记录哪些数据没有获取到，并给出最合理的获取数据的方案，如果方案正确可行，就实施。
- 用alpha-loop 迭代上面这个过程10次。

# 批量分析股票数据(一次分析一只股票)
- 运行此命令 uv run  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260302_gt5p0_20260302_182924.md --start-date 2025-05-30 --analysts-all --limit 1 --show-reasoning --exclude-boards 科创板 北交所
- 此命令会生成每只股票对应的markdown格式的分析报告, 保存到 /Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork/data/reports 目录下, 你仔细分析报告的数据是否有错误，如果有错误，你要仔细说明如何修改，并仔细审阅方案两次修改方案是否正确，如果正确，就按方案进行修改，修改完成后，清除缓存，继续执行上面的命令，检查report，验证修改是否正确，如果有错误，继续修改，直到正确。
- 如果报告中有数据没有获取到，详细记录哪些数据没有获取到，并给出最合理的获取数据的方案，如果方案正确可行，就实施。
- 用alpha-loop 迭代上面这个过程10次。


# 每日批量生成股票分析
- 运行此命令 uv run  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260303_gt5p0_20260303_214747
- .md --start-date 2025-05-30 --analysts-all --show-reasoning --exclude-boards 科创板 北交所  
- 此命令会根据输入文件中的股票，产生大量分析报告，每个股票会生成一个md文件，你耐心等待所有结果生成完成，如果程序中间出现错误，导致程序停止运行。你去检查错误原因，如果能修复就修复问题，问题修复后，继续执行上面这个命令分析股票，直到所有股票分析完毕。


# 推理过程

