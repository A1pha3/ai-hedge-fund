---
难度: ⭐
类型: 入门教程
预计时间: 5 分钟
前置知识:
  - [项目总览](../01-introduction/overview.md) ⭐
---

# 用户手册

本手册面向 A 股每日选股系统的实际使用者,覆盖安装、首次筛选、每日工作流到报告解读的完整链路。系统仅用于教育和研究,不用于实盘交易。

## 读者画像

| 读者类型 | 目标 | 推荐路径 |
|---|---|---|
| 新用户 | 15 分钟跑通第一次筛选 | [快速开始](getting-started.md) → [每日工作流](daily-workflow.md) |
| 运维/部署 | 完成安装与 API 配置 | [安装与配置](installation.md) → [CLI 参考](cli-reference.md) |
| 日常使用者 | 每个交易日稳定拿到 BUY 信号 | [每日工作流](daily-workflow.md) → [报告解读](interpreting-reports.md) |
| 排障者 | 定位命令失败或数据缺失 | [故障排查](troubleshooting.md) → [术语表](glossary.md) |

## 学习路径

### 路径 A:从零到首次筛选(15 分钟)

1. [安装与配置](installation.md)⭐ — 完成 `uv sync` 与 `.env` 配置
2. [快速开始](getting-started.md)⭐ — 跑通 `--auto` 并查看 Top 10 报告

### 路径 B:每日稳定运行(30 分钟)

1. [每日工作流](daily-workflow.md)⭐⭐ — 两条管线的协作与时序
2. [CLI 参考](cli-reference.md)⭐⭐ — 全部命令与参数
3. [报告解读](interpreting-reports.md)⭐⭐ — 读懂 JSON/PDF 输出

### 路径 C:深入理解

1. [架构总览](../03-architecture/overview.md)⭐⭐⭐
2. [设计原则](../04-design/principles.md)⭐⭐⭐

## 文档索引

| 文档 | 难度 | 内容 |
|---|---|---|
| [快速开始](getting-started.md) | ⭐ | 5 步完成首次筛选 |
| [安装与配置](installation.md) | ⭐ | 环境要求、安装步骤、API key |
| [每日工作流](daily-workflow.md) | ⭐⭐ | 交易日时间线、两条管线协作 |
| [CLI 参考](cli-reference.md) | ⭐⭐ | 全部命令与参数详解 |
| [报告解读](interpreting-reports.md) | ⭐⭐ | JSON/PDF 字段含义 |
| [故障排查](troubleshooting.md) | ⭐⭐ | 常见错误与修复 |
| [术语表](glossary.md) | ⭐ | 名词解释 |

## 两条管线速览

系统有两条独立管线,共享缓存但产出不同:

- `--auto`:收盘后跑全市场四策略因子评分,输出 Top 10 推荐到 `data/reports/auto_screening_YYYYMMDD.json`。
- `--daily-action`:读缓存扫描凸性 setup,输出次日 BUY 信号 + Kelly 仓位 + 止损计划,耗时约 3 秒。

`--auto` 是数据底座,`--daily-action` 是交易计划生成器。两条管线不要混用,详见 [每日工作流](daily-workflow.md)。
