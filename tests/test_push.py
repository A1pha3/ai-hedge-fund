"""P2-3 每日选股结果推送 — 单元测试。

覆盖:
  1. 配置文件加载 (含 enabled 过滤)
  2. 邮件发送 (mock SMTP)
  3. 企微 Webhook 发送 (mock HTTP)
  4. 钉钉 Webhook 发送 (mock HTTP)
  5. 通用 Webhook 发送 (mock HTTP)
  6. 失败重试 (3 次后放弃, 不抛异常)
  7. 配置缺失时优雅降级
  8. PDF 附件 (mock, 不真实发送)
  9. 长内容截断 (企微 4096 / 钉钉 20000)
 10. CLI smoke test
 11. build_default_config 助手
 12. Markdown 渲染 (空报告 / 异常值)
 13. email.validate 边界
"""

from __future__ import annotations

import json
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.notification.push import (
    build_default_config,
    EmailConfig,
    format_report_markdown,
    load_push_config,
    MAX_DINGTALK_CONTENT,
    MAX_WECOM_CONTENT,
    PUSH_SCHEMA_VERSION,
    PushChannel,
    PushConfig,
    send_push,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_report() -> dict[str, Any]:
    """合成一份 auto_screening 报告 payload。"""
    return {
        "date": "20260607",
        "top_n": 5,
        "layer_a_count": 80,
        "market_state": {"state_type": "trend", "position_scale": 0.85},
        "recommendations": [
            {
                "ticker": "300750",
                "decision": "buy",
                "score_b": 0.42,
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 78.0},
                    "mean_reversion": {"direction": 0, "confidence": 30.0},
                    "fundamental": {"direction": 1, "confidence": 65.0},
                    "event_sentiment": {"direction": 1, "confidence": 50.0},
                },
            },
            {
                "ticker": "600519",
                "decision": "hold",
                "score_b": 0.15,
                "strategy_signals": {
                    "trend": {"direction": 0, "confidence": 40.0},
                    "mean_reversion": {"direction": 0, "confidence": 35.0},
                    "fundamental": {"direction": 1, "confidence": 70.0},
                    "event_sentiment": {"direction": 0, "confidence": 20.0},
                },
            },
        ],
    }


@pytest.fixture
def wecom_config() -> PushConfig:
    return PushConfig(
        channel=PushChannel.WECOM,
        target="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        enabled=True,
    )


@pytest.fixture
def dingtalk_config() -> PushConfig:
    return PushConfig(
        channel=PushChannel.DINGTALK,
        target="https://oapi.dingtalk.com/robot/send?access_token=test",
        enabled=True,
    )


@pytest.fixture
def email_config() -> PushConfig:
    return PushConfig(
        channel=PushChannel.EMAIL,
        target="user@example.com",
        email=EmailConfig(
            to_addr="user@example.com",
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="bot@example.com",
            smtp_password="secret",
            timeout=10.0,
        ),
        enabled=True,
        include_pdf=False,
    )


@pytest.fixture
def webhook_config() -> PushConfig:
    return PushConfig(
        channel=PushChannel.GENERIC_WEBHOOK,
        target="https://example.com/api/notifications",
        enabled=True,
    )


# ---------------------------------------------------------------------------
# 1. 配置文件加载
# ---------------------------------------------------------------------------


def test_load_push_config_missing_file_returns_empty(tmp_path: Path) -> None:
    """配置文件不存在 → 优雅降级返回空列表。"""
    result = load_push_config(tmp_path / "nonexistent.json")
    assert result == []


def test_load_push_config_filters_disabled(tmp_path: Path) -> None:
    """只加载 enabled=True 的通道。"""
    config_path = tmp_path / "push.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": PUSH_SCHEMA_VERSION,
                "channels": [
                    {"channel": "wecom", "target": "https://w1", "enabled": True},
                    {"channel": "dingtalk", "target": "https://d1", "enabled": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = load_push_config(config_path, only_enabled=True)
    assert len(result) == 1
    assert result[0].channel is PushChannel.WECOM

    # only_enabled=False → 全部加载
    all_configs = load_push_config(config_path, only_enabled=False)
    assert len(all_configs) == 2


def test_load_push_config_corrupt_file_returns_empty(tmp_path: Path) -> None:
    """配置文件 JSON 损坏 → 返回空列表 (不抛异常)。"""
    config_path = tmp_path / "push.json"
    config_path.write_text("{not valid json", encoding="utf-8")
    result = load_push_config(config_path)
    assert result == []


def test_load_push_config_email_with_subconfig(tmp_path: Path) -> None:
    """EMAIL 通道需要解析 email 子对象 — 子字段在顶层 (平铺), 非嵌套在 ``email`` 键。"""
    config_path = tmp_path / "push.json"
    config_path.write_text(
        json.dumps(
            {
                "channels": [
                    {
                        "channel": "email",
                        "target": "alice@example.com",
                        "smtp_host": "smtp.example.com",
                        "smtp_port": 465,
                        "smtp_user": "bot@example.com",
                        "smtp_password_env": "SMTP_PWD",
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    configs = load_push_config(config_path)
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.channel is PushChannel.EMAIL
    assert cfg.email is not None
    assert cfg.email.smtp_host == "smtp.example.com"
    assert cfg.email.smtp_port == 465
    assert cfg.email.smtp_password_env == "SMTP_PWD"


def test_load_push_config_skips_invalid_channel(tmp_path: Path) -> None:
    """非法 channel → 跳过该项, 继续处理其他项。"""
    config_path = tmp_path / "push.json"
    config_path.write_text(
        json.dumps(
            {
                "channels": [
                    {"channel": "unknown_channel", "target": "https://x", "enabled": True},
                    {"channel": "wecom", "target": "https://w1", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    configs = load_push_config(config_path)
    assert len(configs) == 1
    assert configs[0].channel is PushChannel.WECOM


# ---------------------------------------------------------------------------
# 2. 邮件发送
# ---------------------------------------------------------------------------


def test_send_email_uses_smtp_injection(sample_report: dict[str, Any], email_config: PushConfig) -> None:
    """邮件通过注入的 smtp_send_fn 发送, 不真实连接 SMTP。"""
    sent: list[tuple[EmailConfig, MIMEMultipart]] = []

    def fake_smtp_send(cfg: EmailConfig, msg: MIMEMultipart) -> None:
        sent.append((cfg, msg))

    result = send_push(email_config, sample_report, smtp_send_fn=fake_smtp_send)
    assert result.success is True
    assert result.channel is PushChannel.EMAIL
    assert result.attempts == 1
    assert len(sent) == 1
    cfg, msg = sent[0]
    assert cfg.to_addr == "user@example.com"
    assert msg["Subject"] == "AI 选股日报 · 20260607"
    # 邮件正文被 MIMEText 编码为 base64 — 解码后验证内容含 ticker
    from email import policy

    decoded_body = msg.as_string()  # 完整 RFC822 字符串
    # 同时尝试 policy-based 解析 (更现代)
    try:
        from email import message_from_string

        parsed = message_from_string(decoded_body, policy=policy.default)
        text_payload = parsed.get_body(preferencelist=("plain",))
        body_text = text_payload.get_content() if text_payload is not None else decoded_body
    except Exception:
        body_text = decoded_body
    assert "300750" in body_text, f"邮件正文应包含 ticker 300750, 实际: {body_text[:200]}"


def test_send_email_with_pdf_attachment(sample_report: dict[str, Any], email_config: PushConfig, tmp_path: Path) -> None:
    """include_pdf=True + 存在 PDF → 附件被添加。"""
    email_config.include_pdf = True
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%fake pdf content\n%%EOF\n")

    sent: list[tuple[EmailConfig, MIMEMultipart]] = []

    def fake_smtp_send(cfg: EmailConfig, msg: MIMEMultipart) -> None:
        sent.append((cfg, msg))

    result = send_push(email_config, sample_report, pdf_path=pdf_path, smtp_send_fn=fake_smtp_send)
    assert result.success is True
    assert len(sent) == 1
    msg = sent[0][1]
    # 至少包含 2 个 payload part: 文本 + 附件
    assert len(msg.get_payload()) >= 2


def test_send_email_missing_pdf_attachment_silently_continues(
    sample_report: dict[str, Any], email_config: PushConfig, tmp_path: Path
) -> None:
    """include_pdf=True 但 PDF 不存在 → 继续发送纯文本 (warn 一次)。"""
    email_config.include_pdf = True
    non_existent = tmp_path / "missing.pdf"

    sent: list[tuple[EmailConfig, MIMEMultipart]] = []

    def fake_smtp_send(cfg: EmailConfig, msg: MIMEMultipart) -> None:
        sent.append((cfg, msg))

    result = send_push(email_config, sample_report, pdf_path=non_existent, smtp_send_fn=fake_smtp_send)
    assert result.success is True
    assert len(sent) == 1


# ---------------------------------------------------------------------------
# 3-5. Webhook 发送
# ---------------------------------------------------------------------------


def test_send_wecom_webhook(sample_report: dict[str, Any], wecom_config: PushConfig) -> None:
    """企微 Webhook → POST markdown 消息, 期望 HTTP 200。"""
    captured: list[dict[str, Any]] = []

    def fake_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        captured.append({"url": url, "body": body, "timeout": timeout})
        return 200, '{"errcode":0}'

    result = send_push(wecom_config, sample_report, http_post_fn=fake_post)
    assert result.success is True
    assert len(captured) == 1
    req = captured[0]
    assert "qyapi.weixin.qq.com" in req["url"]
    assert req["body"]["msgtype"] == "markdown"
    assert "300750" in req["body"]["markdown"]["content"]


def test_send_dingtalk_webhook(sample_report: dict[str, Any], dingtalk_config: PushConfig) -> None:
    """钉钉 Webhook → POST markdown 消息, 期望 HTTP 200。"""
    captured: list[dict[str, Any]] = []

    def fake_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        captured.append({"url": url, "body": body, "timeout": timeout})
        return 200, '{"errcode":0,"errmsg":"ok"}'

    result = send_push(dingtalk_config, sample_report, http_post_fn=fake_post)
    assert result.success is True
    assert len(captured) == 1
    req = captured[0]
    assert "oapi.dingtalk.com" in req["url"]
    assert req["body"]["msgtype"] == "markdown"
    assert "300750" in req["body"]["markdown"]["text"]


def test_send_generic_webhook(sample_report: dict[str, Any], webhook_config: PushConfig) -> None:
    """通用 Webhook → POST 完整 JSON 载荷, 接受 2xx 状态。"""
    captured: list[dict[str, Any]] = []

    def fake_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        captured.append({"url": url, "body": body})
        return 204, ""

    result = send_push(webhook_config, sample_report, http_post_fn=fake_post)
    assert result.success is True
    assert len(captured) == 1
    req = captured[0]
    assert "subject" in req["body"]
    assert "markdown" in req["body"]
    assert "timestamp" in req["body"]
    assert req["body"]["data"]["date"] == "20260607"


# ---------------------------------------------------------------------------
# 6. 失败重试
# ---------------------------------------------------------------------------


def test_send_push_retries_3_times_on_failure(
    sample_report: dict[str, Any], wecom_config: PushConfig
) -> None:
    """HTTP 持续失败 → 重试 3 次后放弃, 不抛异常, 返回 success=False。"""
    call_count = {"n": 0}

    def always_fail(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        call_count["n"] += 1
        return 500, "internal server error"

    # 避免真实睡眠, 加快测试
    with patch("src.notification.push.time.sleep") as mock_sleep:
        result = send_push(wecom_config, sample_report, http_post_fn=always_fail)

    assert result.success is False
    assert result.attempts == 3
    assert call_count["n"] == 3
    assert "HTTP 500" in (result.error or "")
    # 验证指数退避调用
    assert mock_sleep.call_count == 2  # 重试 3 次, 中间 sleep 2 次


def test_send_push_eventually_succeeds_after_retry(
    sample_report: dict[str, Any], wecom_config: PushConfig
) -> None:
    """前 2 次失败, 第 3 次成功 → 返回 success=True, attempts=3。"""
    call_count = {"n": 0}

    def flaky_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return 503, "service unavailable"
        return 200, '{"errcode":0}'

    with patch("src.notification.push.time.sleep"):
        result = send_push(wecom_config, sample_report, http_post_fn=flaky_post)

    assert result.success is True
    assert result.attempts == 3
    assert call_count["n"] == 3


def test_send_push_disabled_config_returns_success_immediately(
    sample_report: dict[str, Any], wecom_config: PushConfig
) -> None:
    """enabled=False → 视为"未启用", 立即返回 success=True, 不调用 HTTP。"""
    wecom_config.enabled = False

    called = {"n": 0}

    def fake_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        called["n"] += 1
        return 200, ""

    result = send_push(wecom_config, sample_report, http_post_fn=fake_post)
    assert result.success is True
    assert result.attempts == 0
    assert called["n"] == 0  # 未发起任何 HTTP 请求


# ---------------------------------------------------------------------------
# 7. 配置缺失时优雅降级
# ---------------------------------------------------------------------------


def test_load_push_config_root_must_be_dict(tmp_path: Path) -> None:
    """配置文件根节点非 dict → 抛 ValueError。"""
    config_path = tmp_path / "push.json"
    config_path.write_text(json.dumps([{"channel": "wecom"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_push_config(config_path)


def test_load_push_config_channels_must_be_list(tmp_path: Path) -> None:
    """channels 字段非 list → 抛 ValueError。"""
    config_path = tmp_path / "push.json"
    config_path.write_text(json.dumps({"channels": "not a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="'channels' 数组"):
        load_push_config(config_path)


# ---------------------------------------------------------------------------
# 8. PDF 附件 (smtp 调用验证)
# ---------------------------------------------------------------------------


def test_send_email_calls_smtp_with_real_attachment(
    sample_report: dict[str, Any], email_config: PushConfig, tmp_path: Path
) -> None:
    """SMTP 注入函数接收到包含附件的 MIMEMultipart。"""
    email_config.include_pdf = True
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")

    msg_holder: dict[str, MIMEMultipart] = {}

    def capture(cfg: EmailConfig, msg: MIMEMultipart) -> None:
        msg_holder["msg"] = msg

    send_push(email_config, sample_report, pdf_path=pdf_path, smtp_send_fn=capture)
    msg = msg_holder["msg"]
    # 检查附件: 应包含 application/pdf 子类型
    found_pdf = False
    for part in msg.walk():
        if part.get_content_subtype() == "pdf" or part.get("Content-Disposition", "").startswith("attachment"):
            found_pdf = True
            break
    assert found_pdf, "PDF 附件未被检测到"


# ---------------------------------------------------------------------------
# 9. 长内容截断
# ---------------------------------------------------------------------------


def test_wecom_long_content_truncated(sample_report: dict[str, Any], wecom_config: PushConfig) -> None:
    """企微正文 > 4096 字节 → 截断 + truncated=True。"""
    # 制造超长推荐列表
    long_recs = []
    for i in range(500):
        long_recs.append(
            {
                "ticker": f"{600000 + i:06d}",
                "decision": "buy",
                "score_b": 0.5 - i * 0.0001,
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 50.0},
                    "mean_reversion": {"direction": 1, "confidence": 50.0},
                    "fundamental": {"direction": 1, "confidence": 50.0},
                    "event_sentiment": {"direction": 1, "confidence": 50.0},
                },
            }
        )
    sample_report["recommendations"] = long_recs

    captured: list[dict] = []

    def fake_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        captured.append(body)
        return 200, '{"errcode":0}'

    result = send_push(wecom_config, sample_report, http_post_fn=fake_post)
    assert result.success is True
    assert result.truncated is True
    content = captured[0]["markdown"]["content"]
    assert len(content.encode("utf-8")) <= MAX_WECOM_CONTENT + 256  # 截断提示也可能略超
    assert "截断" in content


def test_dingtalk_long_content_truncated(sample_report: dict[str, Any], dingtalk_config: PushConfig) -> None:
    """钉钉正文 > 20000 字节 → 截断。"""
    long_text = "A" * 25_000
    sample_report["recommendations"] = [
        {
            "ticker": "300750",
            "decision": "buy",
            "score_b": 0.5,
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 50.0},
                "mean_reversion": {"direction": 1, "confidence": 50.0},
                "fundamental": {"direction": 1, "confidence": 50.0},
                "event_sentiment": {"direction": 1, "confidence": 50.0},
            },
            "note": long_text,
        }
    ]

    captured: list[dict] = []

    def fake_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
        captured.append(body)
        return 200, '{"errcode":0}'

    result = send_push(dingtalk_config, sample_report, http_post_fn=fake_post)
    assert result.success is True
    assert result.truncated is True
    text = captured[0]["markdown"]["text"]
    assert len(text.encode("utf-8")) <= MAX_DINGTALK_CONTENT + 256


# ---------------------------------------------------------------------------
# 10. CLI smoke test
# ---------------------------------------------------------------------------


def test_main_module_exposes_push_test_entry() -> None:
    """src.main 模块存在 run_push_test 入口 (确保 CLI 集成后能被调用)。"""
    from src import main

    assert hasattr(main, "run_push_test"), "src.main.run_push_test 必须存在"
    assert callable(main.run_push_test)


# ---------------------------------------------------------------------------
# 11. build_default_config 助手
# ---------------------------------------------------------------------------


def test_build_default_config_returns_expected_shape() -> None:
    """build_default_config 返回符合 schema 的 dict。"""
    cfg = build_default_config(
        wecom_url="https://w1",
        dingtalk_url="https://d1",
        email_to="a@b.com",
        enabled_channels=["wecom"],
    )
    assert cfg["schema_version"] == PUSH_SCHEMA_VERSION
    assert len(cfg["channels"]) == 3
    by_channel = {c["channel"]: c for c in cfg["channels"]}
    assert by_channel["wecom"]["enabled"] is True
    assert by_channel["dingtalk"]["enabled"] is False
    assert by_channel["email"]["enabled"] is False
    assert by_channel["email"]["smtp_password_env"] == "SMTP_PASSWORD"


def test_build_default_config_omits_empty() -> None:
    """未提供的通道不写入配置。"""
    cfg = build_default_config(wecom_url="https://w1", enabled_channels=["wecom"])
    assert len(cfg["channels"]) == 1
    assert cfg["channels"][0]["channel"] == "wecom"


# ---------------------------------------------------------------------------
# 12. Markdown 渲染
# ---------------------------------------------------------------------------


def test_format_report_markdown_handles_empty() -> None:
    """空报告 → 渲染出"无推荐"提示。"""
    body = format_report_markdown({"date": "20260607", "recommendations": []})
    assert "AI 选股日报" in body
    assert "无符合条件" in body


def test_format_report_markdown_handles_corrupt_signals() -> None:
    """strategy_signals 字段异常值 → 不抛异常, 渲染 "—"。"""
    body = format_report_markdown(
        {
            "date": "20260607",
            "market_state": {"state_type": "trend", "position_scale": 0.5},
            "recommendations": [
                {
                    "ticker": "300750",
                    "decision": "buy",
                    "score_b": "not a number",  # 异常值
                    "strategy_signals": {
                        "trend": None,  # 异常值
                    },
                }
            ],
        }
    )
    assert "300750" in body
    assert "nan" not in body.lower()  # 不应出现 NaN 字样


def test_format_report_markdown_truncates_table_rows() -> None:
    """max_rows 参数限制展示行数。"""
    recs = []
    for i in range(20):
        recs.append(
            {
                "ticker": f"{600000 + i:06d}",
                "decision": "buy",
                "score_b": 0.5 - i * 0.01,
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 60.0},
                    "mean_reversion": {"direction": 1, "confidence": 60.0},
                    "fundamental": {"direction": 1, "confidence": 60.0},
                    "event_sentiment": {"direction": 1, "confidence": 60.0},
                },
            }
        )
    body = format_report_markdown(
        {"date": "20260607", "recommendations": recs},
        max_rows=3,
    )
    # 仅展示 3 行 + 表头 ("| 1 |" / "| 2 |" / "| 3 |")
    assert "| 1 |" in body
    assert "| 2 |" in body
    assert "| 3 |" in body
    assert "| 4 |" not in body


# ---------------------------------------------------------------------------
# 13. email.validate 边界
# ---------------------------------------------------------------------------


def test_email_config_validate_rejects_bad_to_addr() -> None:
    """to_addr 不含 @ → ValueError。"""
    cfg = EmailConfig(to_addr="not-an-email", smtp_host="smtp.gmail.com", smtp_port=587)
    with pytest.raises(ValueError, match="to_addr"):
        cfg.validate()


def test_email_config_validate_rejects_bad_port() -> None:
    """smtp_port 越界 → ValueError。"""
    cfg = EmailConfig(to_addr="a@b.com", smtp_host="smtp.gmail.com", smtp_port=99999)
    with pytest.raises(ValueError, match="smtp_port"):
        cfg.validate()


def test_email_config_resolves_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """smtp_password_env 优先于明文 smtp_password。"""
    monkeypatch.setenv("MY_SMTP_PWD", "env-secret")
    cfg = EmailConfig(
        to_addr="a@b.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_password="plain-secret",
        smtp_password_env="MY_SMTP_PWD",
    )
    assert cfg.resolved_password() == "env-secret"


# ---------------------------------------------------------------------------
# 14. PushConfig.validate 边界
# ---------------------------------------------------------------------------


def test_push_config_validate_requires_email_for_email_channel() -> None:
    """EMAIL 通道但 email 子对象为 None → ValueError。"""
    cfg = PushConfig(channel=PushChannel.EMAIL, target="a@b.com", email=None)
    with pytest.raises(ValueError, match="EMAIL 通道必须提供 email"):
        cfg.validate()


def test_push_config_validate_rejects_empty_target() -> None:
    """target 为空 → ValueError。"""
    cfg = PushConfig(channel=PushChannel.WECOM, target="", enabled=True)
    with pytest.raises(ValueError, match="target"):
        cfg.validate()


# ---------------------------------------------------------------------------
# 15. PushResult.to_dict
# ---------------------------------------------------------------------------


def test_push_result_to_dict_shape() -> None:
    """PushResult.to_dict 返回包含关键字段的 dict。"""
    from src.notification.push import PushResult

    r = PushResult(
        channel=PushChannel.WECOM,
        target="https://w1",
        success=True,
        attempts=1,
        duration_ms=12.3,
        truncated=False,
    )
    d = r.to_dict()
    assert d["channel"] == "wecom"
    assert d["success"] is True
    assert d["attempts"] == 1
    assert d["duration_ms"] == 12.3
    assert d["truncated"] is False
    assert d["error"] is None
