import json


def build_reasoning_signal_section(section_title: str, value: dict) -> list[str]:
    lines: list[str] = []
    signal_type = value.get("signal", "").upper()
    confidence = value.get("confidence", "")
    details = value.get("details", "")
    metrics = value.get("metrics", {})

    signal_emoji = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "⚖️"}.get(signal_type, "❓")
    title_suffix = f" ({signal_emoji} {signal_type})" if signal_type else ""
    lines.append(f"\n**{section_title}**{title_suffix}")
    if confidence != "":
        lines.append(f"- 置信度: {confidence}%")
    if details:
        lines.append(f"- 详情: {details}")

    if metrics:
        lines.extend(_build_metrics_table(metrics))

    articles = value.get("articles", [])
    if articles:
        lines.extend(_build_articles_section(articles))
    return lines


def build_reasoning_dict_section(section_title: str, value: dict) -> list[str]:
    lines = [f"\n**{section_title}**", "", "| 字段 | 值 |", "|------|------|"]
    for sub_key, sub_value in value.items():
        field_name = sub_key.replace("_", " ").title()
        if sub_value is None:
            lines.append(f"| {field_name} | N/A |")
        elif isinstance(sub_value, float):
            lines.append(f"| {field_name} | {sub_value:.4f} |")
        else:
            lines.append(f"| {field_name} | {sub_value} |")
    return lines


def build_reasoning_fallback_table(reasoning: dict) -> list[str]:
    lines = ["", "| 字段 | 值 |", "|------|------|"]
    for key, value in reasoning.items():
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, ensure_ascii=False)
        else:
            value_str = str(value)
        lines.append(f"| {key} | {value_str} |")
    return lines


def _build_metrics_table(metrics: dict) -> list[str]:
    lines = ["", "| 指标 | 值 |", "|------|------|"]
    for metric_key, metric_value in metrics.items():
        metric_name = metric_key.replace("_", " ").title()
        if metric_value is None:
            lines.append(f"| {metric_name} | N/A |")
        elif isinstance(metric_value, float):
            lines.append(f"| {metric_name} | {metric_value:.4f} |")
        else:
            lines.append(f"| {metric_name} | {metric_value} |")
    return lines


def _build_articles_section(articles: list[dict]) -> list[str]:
    sorted_articles = sorted(articles, key=lambda article: article.get("date", ""), reverse=True)
    lines = ["", "**新闻文章列表**\n", "| # | 日期 | 情感 | 来源 | 标题 |", "|---|------|------|------|------|"]
    for index, article in enumerate(sorted_articles, 1):
        title = article.get("title", "")
        url = article.get("url", "")
        date = article.get("date", "")
        source = article.get("source", "")
        sentiment = article.get("sentiment", "")
        sentiment_emoji = {"正面": "🟢", "负面": "🔴", "中性": "⚪"}.get(sentiment, "⚪")
        title_cell = f"[{title}]({url})" if url else title
        lines.append(f"| {index} | {date} | {sentiment_emoji} {sentiment} | {source} | {title_cell} |")

    summaries = [(index, article) for index, article in enumerate(sorted_articles, 1) if article.get("summary")]
    if summaries:
        lines.append("")
        lines.append("**文章摘要**\n")
        for index, article in summaries:
            lines.append(f"{index}. **{article['title'][:30]}...**: {article['summary']}")
    return lines
