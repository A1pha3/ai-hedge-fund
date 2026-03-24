# 数据缓存复用手册

## 1. 这份手册解决什么问题

当你多次运行重叠时间窗口的选股、frozen replay 或 paper trading 时，如果每次都重新向 Tushare 和 AKShare 拉同一批行情与基础数据，运行会同时变慢、变脆弱，还更容易触发上游频率限制。

当前项目已经把高频市场数据接到了本地多层缓存：

1. 进程内热点命中走 LRU 内存缓存。
2. 跨进程复用走本地 SQLite 磁盘缓存。
3. 如果环境里有 Redis，还可以继续向上扩展共享层。

这份手册只回答三件事：

1. 缓存放在哪里。
2. 怎么看缓存是不是在工作。
3. 怎么验证重复运行确实复用了历史数据。

---

## 2. 缓存默认放在哪里

默认磁盘路径：

```bash
~/.cache/ai-hedge-fund/cache.sqlite
```

如果你想把缓存放到别的位置，可以在运行前设置：

```bash
DISK_CACHE_PATH=/custom/path/cache.sqlite
```

适合自定义路径的场景：

1. 你想把缓存放到更大的磁盘。
2. 你想对不同实验使用不同 cache 文件。
3. 你想在清理实验目录时一起管理缓存生命周期。

---

## 3. 怎么看缓存当前状态

查看缓存运行时信息：

```bash
.venv/bin/python scripts/manage_data_cache.py stats
```

返回结果会包含：

1. `lru_maxsize`
2. `redis_available`
3. `disk_available`
4. `disk_path`
5. `stats`

其中 `stats` 最重要，常见字段含义如下：

1. `lru_hits`：当前进程内存命中次数。
2. `redis_hits`：Redis 命中次数。
3. `disk_hits`：磁盘缓存命中次数。
4. `misses`：缓存未命中次数。
5. `sets`：新写入缓存次数。
6. `total_requests`：总请求数。
7. `hit_rate`：总体命中率。

如果你想把结果存档到 report 目录：

```bash
.venv/bin/python scripts/manage_data_cache.py stats \
  --output data/reports/data_cache_stats.json
```

---

## 4. 什么时候应该清缓存

以下情况适合主动清缓存：

1. 你改了数据拉取逻辑，怀疑旧缓存和新 schema 不兼容。
2. 你想做首跑与复跑的对照实验。
3. 你怀疑某次异常数据已经落盘，希望重新取源站数据。

清缓存命令：

```bash
.venv/bin/python scripts/manage_data_cache.py clear --yes
```

这里要求显式传 `--yes`，是为了避免误删本地缓存。

---

## 5. 怎么验证复用真的生效

最直接的方法是使用项目内置脚本：

```bash
source .env && \
.venv/bin/python scripts/validate_data_cache_reuse.py \
  --trade-date 20260305 \
  --ticker 300724 \
  --output data/reports/data_cache_reuse_20260305.json
```

这个脚本会直接调用几类高频数据路径：

1. `get_all_stock_basic`
2. `get_daily_basic_batch`
3. `get_limit_list`
4. `get_suspend_list`
5. `get_stock_details`

你应该这样看结果：

### 第一次运行

通常会看到：

1. `misses` 增加。
2. `sets` 增加。
3. `disk_hits` 很少或为 0。

这说明缓存正在写入，而不是已经复用。

### 第二次运行同一条命令

通常会看到：

1. `disk_hits` 明显增加。
2. `misses` 接近 0。
3. `sets` 接近 0。

这说明第二次运行已经在复用第一次落盘的数据。

项目中已经做过一次真实验证，结果是：

1. 第一次运行：`misses=6`, `sets=6`, `disk_hits=0`
2. 第二次运行：`disk_hits=6`, `misses=0`, `sets=0`, `hit_rate=1.0`

这说明跨进程 SQLite 复用链路已经实际跑通。

---

## 6. 在 paper trading 结果里怎么看 cache

paper trading 运行结束后，`session_summary.json` 现在会记录：

1. `data_cache`
2. `data_cache.session_stats`
3. `artifacts.data_cache_path`

这三块分别回答：

1. 当前会话结束时整体缓存状态是什么。
2. 本次运行相对起点新增了多少 hit 或 miss。
3. 实际落盘使用的是哪个 cache 文件。

这意味着你不需要额外翻日志，也能直接在单次运行产物里判断 cache 是否有效参与了这次执行。

---

## 7. 常见误区

1. `hit_rate` 高，不代表所有数据都来自磁盘，也可能是 LRU 命中。
2. 第一次跑 miss 多，不是坏事，这通常只是缓存开始建档。
3. 不 source `.env` 就跑验证脚本，可能因为缺少 Tushare 配置而得到空结果。
4. 清缓存只适合做对照实验或 schema 切换，不适合日常每次运行前都执行。

---

## 8. 推荐日常操作顺序

如果你只是想确认当前一组重叠窗口是否已经享受到缓存收益，最小流程如下：

1. 先执行 `stats` 看当前 cache 路径和累计命中。
2. 跑一次目标窗口。
3. 再看 `session_summary.json` 里的 `data_cache.session_stats`。
4. 如果要做严格对照，再 `clear --yes` 后重复一次。
5. 如果要做独立证明，再跑 `validate_data_cache_reuse.py` 两次对比。

这套流程已经足够区分三种情况：

1. 缓存根本没启用。
2. 缓存已启用，但只在单进程内生效。
3. 缓存已启用，并且跨进程磁盘复用正常。
