from datetime import datetime
from types import SimpleNamespace

from src.utils import display


class _FrozenDateTime:
    @classmethod
    def now(cls):
        return datetime(2026, 4, 10, 9, 30, 0)


def test_format_reasoning_to_markdown_renders_signal_sections_and_articles():
    reasoning = {
        "news_sentiment": {
            "signal": "bullish",
            "confidence": 72,
            "details": "Momentum improving",
            "metrics": {"score": 0.12345, "headline_count": 3, "missing": None},
            "articles": [
                {"title": "Older note", "date": "2026-04-08", "source": "A", "sentiment": "中性"},
                {"title": "Latest note", "date": "2026-04-09", "source": "B", "sentiment": "正面", "url": "https://example.com/latest", "summary": "Latest summary"},
            ],
        },
        "combined_analysis": {"score": 1.2, "verdict": "watch"},
        "analysis": "Overall constructive.",
    }

    rendered = display._format_reasoning_to_markdown(reasoning)

    assert "**News Sentiment** (📈 BULLISH)" in rendered
    assert "- 置信度: 72%" in rendered
    assert "| Score | 0.1235 |" in rendered
    assert "| Missing | N/A |" in rendered
    assert "| 1 | 2026-04-09 | 🟢 正面 | B | [Latest note](https://example.com/latest) |" in rendered
    assert "| 2 | 2026-04-08 | ⚪ 中性 | A | Older note |" in rendered
    assert "**Combined Analysis**" in rendered
    assert "**分析说明**: Overall constructive." in rendered


def test_save_trading_report_writes_current_markdown_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(display, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(display, "datetime", _FrozenDateTime)
    monkeypatch.setattr(
        display,
        "get_stock_details",
        lambda ticker: {
            "name": "平安银行",
            "pct_chg": 1.23,
            "pre_close": 10.0,
            "close": 10.5,
            "area": "深圳",
            "industry": "银行",
            "market": "主板",
            "list_date": "19910403",
        },
    )
    monkeypatch.setattr(display, "get_stock_name", lambda ticker: "平安银行")

    result = {
        "decisions": {
            "000001": {
                "action": "buy",
                "quantity": 100,
                "confidence": 82.5,
                "reasoning": "Breakout confirmed.",
            }
        },
        "analyst_signals": {
            "news_sentiment_agent": {
                "000001": {
                    "signal": "bullish",
                    "confidence": 75,
                    "reasoning": {
                        "news_sentiment": {
                            "signal": "bullish",
                            "confidence": 75,
                            "details": "News flow strong",
                            "metrics": {"score": 0.5},
                        }
                    },
                    "reasoning_cn": "中文推理",
                }
            },
            "risk_management_agent": {
                "000001": {
                    "remaining_position_limit": 120000.0,
                    "current_price": 10.5,
                    "volatility_metrics": {
                        "daily_volatility": 0.0123,
                        "annualized_volatility": 0.2345,
                        "volatility_percentile": 66.6,
                        "data_points": 20,
                    },
                    "reasoning": {
                        "portfolio_value": 500000.0,
                        "current_position_value": 100000.0,
                        "base_position_limit_pct": 0.1,
                        "combined_position_limit_pct": 0.2,
                        "available_cash": 300000.0,
                        "risk_adjustment": "Moderate",
                    },
                }
            },
        },
    }

    report_path = display.save_trading_report(
        result=result,
        tickers=["000001"],
        model_name="gpt-4.1",
        model_provider="OpenAI",
        start_date="2026-04-01",
        end_date="2026-04-10",
    )

    assert report_path == tmp_path / "000001_20260410_093000.md"
    content = report_path.read_text(encoding="utf-8")
    assert "# 对冲基金分析报告" in content
    assert "- **生成时间**: 2026-04-10 09:30:00" in content
    assert "| 000001 | 平安银行 | 1.23 | 10.0 | 10.5 | 深圳 | 银行 | 主板 | 1991-04-03 | BUY | 82.5% |" in content
    assert "### 1. 分析师信号汇总" in content
    assert "| News Sentiment | BULLISH | 75% |" in content
    assert "**News Sentiment** (📈 BULLISH)" in content
    assert "**中文翻译**：" in content
    assert "### 3. 风险管理分析" in content
    assert "| 投资组合价值 | ¥500,000.00 |" in content
    assert "| 操作 | 📈 **BUY** |" in content


def test_print_trading_output_renders_current_console_contract(monkeypatch, capsys):
    monkeypatch.setattr(display, "Fore", SimpleNamespace(RED="", WHITE="", BRIGHT="", CYAN="", GREEN="", YELLOW=""))
    monkeypatch.setattr(display, "Style", SimpleNamespace(RESET_ALL="", BRIGHT=""))
    monkeypatch.setattr(display, "tabulate", lambda rows, **kwargs: f"TABULATE[{len(rows)}]")
    monkeypatch.setattr(display.logger, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(display.logger, "warning", lambda *args, **kwargs: None)

    result = {
        "decisions": {
            "000001": {
                "action": "buy",
                "quantity": 100,
                "confidence": 82.5,
                "reasoning": "This is a long reasoning string that should wrap across multiple words for the table output contract.",
            }
        },
        "analyst_signals": {
            "technical_analyst_agent": {
                "000001": {
                    "signal": "bullish",
                    "confidence": 70,
                    "reasoning": {"trend": "strong"},
                }
            },
            "risk_management_agent": {
                "000001": {
                    "signal": "neutral",
                    "confidence": 55,
                }
            },
        },
    }

    display.print_trading_output(result)

    stdout = capsys.readouterr().out
    assert "Analysis for 000001" in stdout
    assert "AGENT ANALYSIS: [000001]" in stdout
    assert "TRADING DECISION: [000001]" in stdout
    assert "PORTFOLIO SUMMARY:" in stdout
    assert "Portfolio Strategy:" in stdout
    assert "TABULATE[1]" in stdout
    assert "TABULATE[4]" in stdout


def test_print_trading_output_warns_when_decisions_missing(monkeypatch, capsys):
    monkeypatch.setattr(display, "Fore", SimpleNamespace(RED=""))
    monkeypatch.setattr(display, "Style", SimpleNamespace(RESET_ALL=""))
    monkeypatch.setattr(display.logger, "warning", lambda *args, **kwargs: None)

    display.print_trading_output({})

    assert "No trading decisions available" in capsys.readouterr().out
