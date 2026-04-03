# 核心后端问题分析

> 范围：`src/agents/`、`src/tools/`、`src/data/`、`src/graph/`、`src/utils/`、`src/main.py`

---

## 总结

核心 Python 层的主要问题不是“某一个函数写错”，而是**可靠性、线程安全、异常治理和数据可信度**同时存在短板。尤其是数据采集层与 agent 推理层之间缺少强约束，已经出现了“LLM 编造数据”的明确信号，这会直接影响交易结论可信度。

---

## 一、严重问题

### 1. LLM 数据可信度存在实证风险

- **现象**：仓库根目录存在专门的排查脚本 `debug_data_analysis.py` 与修复脚本 `fix_agent_prompts.py`
- **含义**：这不是推测，而是项目历史上已经出现过 agent 产出与真实数据不一致的问题
- **风险**：
  - 生成虚假的财务指标、估值依据、交易理由
  - 组合决策建立在错误事实之上
  - 回测结果和实盘模拟都可能被污染

**结论**：这是当前系统最关键的问题之一，优先级高于一般代码整洁性问题。

### 2. `akshare` 代理绕过方案线程不安全

- **证据**：`src/tools/akshare_api.py:205-222`
- **问题**：运行时直接改写 `requests.get`、`requests.post`、`requests.Session.get`、`requests.Session.request`
- **风险**：
  - 并发执行时，全局 HTTP 行为被污染
  - 其他模块可能在同一时刻读到被篡改后的 requests 行为
  - 难以排查的随机故障、代理失效、请求串扰

这类“猴子补丁”只适合一次性脚本，不适合多 agent、多请求的长期运行服务。

### 3. 图状态类型定义存在基础错误

- **证据**：`src/graph/state.py:8,15,16`
- **问题**：使用了 `dict[str, any]`，而不是 `dict[str, Any]`
- **影响**：
  - 类型提示失效
  - 静态检查无法发现真实问题
  - 暗示状态结构本身缺少严格约束

### 4. 图状态合并策略过于粗糙

- **证据**：`src/graph/state.py:8-16`
- **问题**：`merge_dicts()` 为浅合并
- **风险**：
  - 嵌套字段被后写入的数据整体覆盖
  - 多 agent 写入共享 state 时可能互相踩数据
  - 问题表现通常不是报错，而是“结果不完整”或“偶发缺字段”

---

## 二、高风险问题

### 1. 大量宽泛异常捕获导致真实故障被吞掉

重点区域：

- `src/tools/api.py`
- `src/tools/tushare_api.py`
- `src/tools/akshare_api.py`
- `src/agents/risk_manager.py`
- `src/screening/candidate_pool.py`

主要表现：

- 使用 bare `except:` 或 `except Exception:`
- 返回空列表、空对象或默认值
- 缺少上下文日志

后果：

1. 上游失败被伪装成“无数据”
2. 下游 agent 继续推理，导致错误扩散
3. 排障时无法区分“接口失败”和“市场本来就没数据”

### 2. `tushare` 内存缓存无上限

- **证据**：`src/tools/tushare_api.py:18-19` 定义 `_tushare_df_cache`
- **补充证据**：文件中大量位置持续向该缓存写入
- **问题**：缓存无 TTL、无 size limit、无 eviction policy
- **风险**：
  - 长时间运行后内存持续膨胀
  - DataFrame 占用大，容易造成 OOM
  - 本地调试和短任务可能不明显，线上/批量回测会集中暴露

### 3. 全局共享状态较多，线程安全不足

重点区域：

- `src/tools/tushare_api.py`
- `src/tools/akshare_api.py`

问题包括：

- 全局缓存
- 全局 provider 对象
- 部分资源有锁，部分没有锁
- 多 agent 并发时读写边界不清晰

### 4. 同步阻塞调用影响并发吞吐

重点区域：

- `src/tools/api.py`
- `src/tools/tushare_api.py`
- `src/utils/llm.py`

问题：

- 使用 `time.sleep()` 做限流与重试
- 在多 agent 工作流中直接阻塞线程

影响：

- 并发分析时整体吞吐下降
- 用户看到“卡住”，但实际上是 sleep 堵塞
- 未来扩容时效率很差

### 5. 多 agent 数据获取存在 N+1 式串行访问

例如：

- `src/agents/warren_buffett.py`
- `src/agents/risk_manager.py`

问题模式：

- 对每个 ticker 分别请求多次指标、财报、价格、估值
- 没有批量抓取、共享结果或跨 agent 复用

结果：

- token 与 API 请求数放大
- 分析延迟高
- 限流与失败率同步上升

---

## 三、中风险问题

### 1. 数值计算边界检查不足

例如：

- `src/agents/warren_buffett.py` 中存在除以 `market_cap` 的风险
- `src/agents/portfolio_manager.py` 中把风险管理器返回值直接转为 `float`

这类问题一旦碰到 `None`、`0`、空字符串，就会导致：

- `ZeroDivisionError`
- `ValueError`
- 或更糟：错误默认值进入后续计算

### 2. 工作流消息状态可能无限增长

- **证据**：`src/main.py` 中 state message 采用累加写法
- **问题**：消息不断 append，没有明确裁剪策略
- **风险**：
  - 上下文越来越大
  - LLM 调用成本上升
  - 历史噪音影响后续决策

### 3. 环境变量治理较弱

例如：

- `ANALYST_CONCURRENCY_LIMIT` 非法时静默回退默认值
- snapshot 相关开关缺少集中验证

问题在于：

- 配错了也不明显
- 系统会“带病运行”
- 结果异常但不易归因到配置

### 4. 打印日志替代结构化日志

项目内存在大量 `print()` 调用，尤其是数据源相关模块。

影响：

- 无法统一收集
- 缺少 trace / request / ticker / provider 等结构化字段
- 线上排障效率低

### 5. 魔法数字较多

例如风险系数、波动率裁剪边界、相关性阈值等大量直接硬编码在逻辑里。

风险：

- 业务含义不透明
- 参数无法集中管理
- 调优只能改代码

---

## 四、架构层问题

### 1. 数据采集、清洗、推理、决策之间缺少硬边界

当前系统链路大致是：

`provider -> tools -> agents -> risk manager -> portfolio manager`

但中间缺少：

- 统一的数据契约
- 来源可信度标记
- 数据缺失等级
- 置信度与事实证据绑定

这导致 agent 很容易在“缺数据”“坏数据”“旧数据”情况下继续做出看似完整的结论。

### 2. 缺少统一的错误语义

现在常见情况是：

- 有的函数返回空列表
- 有的返回默认值
- 有的直接抛异常
- 有的打印错误后继续

建议定义统一语义，例如：

- `DataUnavailable`
- `ProviderTemporaryFailure`
- `SchemaValidationFailed`
- `UnsupportedTicker`

否则上层无法做正确的重试、降级、告警。

### 3. 缺少系统级观测指标

当前最缺的不是“更多日志”，而是关键指标：

- provider 成功率
- cache hit rate
- 每个 ticker 的数据完整度
- agent 输出中引用证据占比
- hallucination 检测命中率

没有这些指标，就很难把系统从“能跑”提升到“可信”。

---

## 五、建议修复顺序

### 第一阶段：先处理 correctness

1. 为 agent 输出增加“事实来源校验”
2. 明确数据缺失时禁止继续生成确定性结论
3. 清理宽泛异常捕获，改为明确异常类型
4. 禁止全局 monkey patch requests

### 第二阶段：处理稳定性

1. 为 tushare/akshare 缓存增加上限和 TTL
2. 将阻塞式 sleep 改为更可控的限流机制
3. 对共享状态加锁或改为实例隔离
4. 控制消息 state 长度

### 第三阶段：处理可维护性

1. 修正 `Any` 类型和状态结构定义
2. 收敛魔法数字到配置层
3. 将 `print()` 统一替换为结构化日志
4. 抽象统一的数据质量与 provider 错误模型

---

## 六、核心判断

这个系统的核心后端目前**最大的问题不是功能不全，而是结果可信度与运行稳定性不足**。如果未来要把它用于长期研究、批量回测、甚至准实时模拟，必须优先解决：

1. 数据真实性
2. 并发安全
3. 错误透明度
4. 缓存与状态治理
