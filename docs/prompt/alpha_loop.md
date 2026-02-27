# 分析单只股票

- 运行此命令会生成report ./scripts/run-hedge-fund.sh --ticker 300118 --model MiniMax-M2.5 --start-date 2025-06-01 --analysts-all --show-reasoning 你仔细分析report中的数据是否有问题，是否符合预期，如果有问题，及时修改，
并说明为何如此修改，然后继续执行命令，检查数据验证，修改。用alpha-loop 迭代这个过程，直到数据没有问题。 


# 批量分析股票
- 运行此命令 uv run  python scripts/batch_run_hedge_fund.py --file data/stock/daliy/daily_gainers_20260226_gt5p0_20260226_233140.md --model MiniMax-M2.5 --start-date 2025-06-
- 01 --analysts-all  --show-reasoning 会生成report,你仔细分析report中的数据是否有问题，是否符合预期，如果有问题，你要仔细说明为何如此修改，审阅修改方案是否正确，如果正确，就按方案进行修改，修改完成后，继续执行命令来检查和验证数据是否有问题。用alpha-loop 迭代这个过程，直到数据没有问题。