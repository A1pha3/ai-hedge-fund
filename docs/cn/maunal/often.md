# 完整操作指南

每日选股流程（2 个命令）
bash
# 1. 收盘后更新数据（~4PM 后跑，需要 tushare token）
uv run python src/main.py --auto

# 2. 获取今日选股信号（~3 秒，从缓存读）
uv run python src/main.py --daily-action
关键澄清
--auto 和 --daily-action 是两套独立系统：

--auto = 4 策略融合评分（趋势/均值回归/基本面/事件情绪）→ 产出 score_b 排名。不用 BTST，不扫涨停。它的作用是更新数据缓存 + 生成市场状态
--daily-action = 凸性 setup 扫描（BTST 涨停突破 + OversoldBounce 超跌反弹）→ 产出具体 BUY 信号。直扫全市场 price_cache，不依赖 --auto 的候选池
所以：刷新数据用 --auto，看选股信号用 --daily-action。

数据日期
--auto：用系统当天日期，必须在收盘后跑（盘中跑会因数据未更新而报错）
--daily-action：自动取 price_cache 最新交易日。如果今天的 --auto 还没跑，它会用昨天的数据
建议：每天收盘后先 --auto（更新缓存），再 --daily-action（用最新数据出信号）。