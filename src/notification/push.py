"""P2-3 每日选股结果推送 — 邮件 / 企微 / 钉钉 / 通用 Webhook。

设计原则:
  - **离线优先**: 所有 HTTP/SMTP 调用通过接口注入, 单元测试可完全 mock。
  - **失败容错**: 网络/认证/超时错误统一捕获, 返回 ``PushResult(success=False)`` 而不抛异常。
  - **优雅降级**: 配置文件不存在 / 解析失败 / 无 enabled channel → 静默返回 True (视为"未启用")。
  - **可重入**: 每次推送独立 retry 3 次, 指数退避 (避免雪崩), 不修改全局状态。

支持 4 种通道:
  - ``EMAIL``         — SMTP 邮件 (可选 PDF 附件)
  - ``WECOM``         — 企微机器人 Webhook
  - ``DINGTALK``      — 钉钉机器人 Webhook
  - ``GENERIC_WEBHOOK`` — 通用 JSON POST Webhook
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.utils.numeric import safe_float as _safe_float

logger = logging.getLogger(__name__)


PUSH_VERSION = "1.0.0"
"""推送模块版本号。"""
PUSH_SCHEMA_VERSION = 1
"""推送配置 JSON schema 版本。"""

DEFAULT_PUSH_CONFIG_PATH = Path("data") / "push_config.json"
"""默认配置文件路径 (相对 cwd)。"""

MAX_WECOM_CONTENT = 4096
"""企微机器人单条消息最大字节数 (UTF-8)。"""
MAX_DINGTALK_CONTENT = 20_000
"""钉钉机器人单条消息最大字节数 (UTF-8)。"""

MAX_RETRIES = 3
"""单次推送最大重试次数。"""
RETRY_BACKOFF_BASE = 0.5
"""重试指数退避基准 (秒): sleep = base * (2 ** attempt)。"""

# 依赖注入点 (供测试 monkeypatch 使用)
SmtpSendFn = Callable[["EmailConfig", "MIMEMultipart"], None]
HttpPostFn = Callable[[str, dict[str, str], dict[str, Any], float], tuple[int, str]]


def _default_smtp_send(cfg: "EmailConfig", msg: MIMEMultipart) -> None:
    """默认 SMTP 发送实现 — 单元测试通常会 monkeypatch 此函数。"""
    password = os.environ.get(cfg.smtp_password_env, "") if cfg.smtp_password_env else cfg.smtp_password
    if not password:
        raise RuntimeError(f"SMTP 密码未配置: 环境变量 {cfg.smtp_password_env} 不存在或为空")
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.timeout) as server:
        server.starttls()
        server.login(cfg.smtp_user, password)
        server.sendmail(cfg.smtp_user, [cfg.to_addr], msg.as_string())


def _default_http_post(url: str, headers: Mapping[str, str], body: dict[str, Any], timeout: float) -> tuple[int, str]:
    """默认 HTTP POST 实现 — 使用 urllib (无第三方依赖)。

    单元测试通常会 monkeypatch 此函数。返回 ``(status_code, response_text)``。
    """
    import urllib.error
    import urllib.request

    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace") if exc.fp else ""


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


class PushChannel(Enum):
    """推送通道类型。"""

    EMAIL = "email"
    WECOM = "wecom"
    DINGTALK = "dingtalk"
    GENERIC_WEBHOOK = "webhook"


@dataclass
class EmailConfig:
    """SMTP 邮件配置。"""

    to_addr: str
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # 明文 (优先级低); 推荐用 smtp_password_env
    smtp_password_env: str = ""  # 环境变量名, 推荐做法
    timeout: float = 15.0

    def resolved_password(self) -> str:
        """优先从环境变量读取密码, 退回明文字段。"""
        if self.smtp_password_env:
            return os.environ.get(self.smtp_password_env, "")
        return self.smtp_password

    def validate(self) -> None:
        if not self.to_addr or "@" not in self.to_addr:
            raise ValueError(f"EmailConfig.to_addr 非法: {self.to_addr!r}")
        if not self.smtp_host:
            raise ValueError("EmailConfig.smtp_host 不能为空")
        if not (1 <= int(self.smtp_port) <= 65535):
            raise ValueError(f"EmailConfig.smtp_port 越界: {self.smtp_port}")


@dataclass
class PushConfig:
    """单个推送通道的完整配置。"""

    channel: PushChannel
    target: str  # 邮件地址 / Webhook URL
    enabled: bool = True
    subject_template: str = "AI 选股日报 · {date}"
    include_pdf: bool = True
    email: EmailConfig | None = None  # 仅 EMAIL 通道使用
    timeout: float = 15.0
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.channel, PushChannel):
            raise ValueError(f"channel 必须为 PushChannel 枚举, 实际: {type(self.channel).__name__}")
        if not self.target or not str(self.target).strip():
            raise ValueError(f"target 不能为空 (channel={self.channel.value})")
        if self.channel is PushChannel.EMAIL and self.email is None:
            raise ValueError("EMAIL 通道必须提供 email 配置")


@dataclass
class PushPayload:
    """单次推送的有效载荷。"""

    subject: str
    markdown_body: str
    json_body: dict[str, Any] = field(default_factory=dict)
    pdf_path: Path | None = None


@dataclass
class PushResult:
    """单次推送的执行结果。"""

    channel: PushChannel
    target: str
    success: bool
    attempts: int = 0
    error: str | None = None
    duration_ms: float = 0.0
    truncated: bool = False  # 消息被截断时为 True

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel.value,
            "target": self.target,
            "success": self.success,
            "attempts": self.attempts,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def _safe_str(value: Any, default: str = "") -> str:
    """安全字符串化 — None / 异常值 → default。"""
    if value is None:
        return default
    try:
        return str(value)
    except (TypeError, ValueError):
        return default


def format_report_markdown(report_data: Mapping[str, Any], *, max_rows: int = 10) -> str:
    """把 auto_screening 报告渲染成 Markdown 摘要 (供邮件/企微/钉钉正文)。

    Args:
        report_data: ``compute_auto_screening_results`` 返回的 payload (含
            ``date`` / ``recommendations`` / ``market_state`` / ``top_n``)。
        max_rows: 推荐标的最多展示多少行 (默认 10)。

    Returns:
        UTF-8 Markdown 字符串, 不会抛异常 — 输入异常时返回最小可用内容。
    """
    date = _safe_str(report_data.get("date"), datetime.now().strftime("%Y%m%d"))
    recs_raw = report_data.get("recommendations") or []
    if not isinstance(recs_raw, list):
        recs_raw = []

    market_state_raw = report_data.get("market_state")
    if isinstance(market_state_raw, Mapping):
        state_type = _safe_str(market_state_raw.get("state_type"), "mixed")
        position_scale = _safe_float(market_state_raw.get("position_scale"), 1.0)
    else:
        state_type = "mixed"
        position_scale = 1.0

    lines: list[str] = []
    lines.append(f"# AI 选股日报 · {date}")
    lines.append("")
    lines.append(f"- 市场状态: `{state_type}` · 仓位系数 `{position_scale:.2f}`")
    lines.append(f"- 推荐数量: {len(recs_raw)}")
    lines.append("")

    if not recs_raw:
        lines.append("> 今日无符合条件的推荐标的。")
        return "\n".join(lines)

    lines.append("## 推荐标的")
    lines.append("")
    lines.append("| # | 代码 | 决策 | 评分 | 趋势 | 反转 | 基本面 | 事件 |")
    lines.append("|---|------|------|------|------|------|--------|------|")
    for idx, rec in enumerate(recs_raw[:max_rows], 1):
        if not isinstance(rec, Mapping):
            continue
        ticker = _safe_str(rec.get("ticker"), "-")
        decision = _safe_str(rec.get("decision"), "-")
        score_b = _safe_float(rec.get("score_b"), 0.0)
        signals = rec.get("strategy_signals") or {}
        if not isinstance(signals, Mapping):
            signals = {}

        def _sig(name: str) -> str:
            sig = signals.get(name)
            if not isinstance(sig, Mapping):
                return "—"
            direction = _safe_float(sig.get("direction"), 0.0)
            confidence = _safe_float(sig.get("confidence"), 0.0)
            arrow = "↑" if direction > 0 else "↓" if direction < 0 else "—"
            return f"{arrow}{confidence:.0f}"

        lines.append(f"| {idx} | {ticker} | {decision} | {score_b:+.4f} | " f"{_sig('trend')} | {_sig('mean_reversion')} | {_sig('fundamental')} | {_sig('event_sentiment')} |")
    lines.append("")
    if len(recs_raw) > max_rows:
        lines.append(f"_仅展示 Top {max_rows} / 共 {len(recs_raw)} 条。完整内容请查看 JSON 报告。_")

    # 附加: 备注/事件/逻辑说明 (在表格后追加, 用于长内容截断测试)
    notes_section: list[str] = []
    for rec in recs_raw[:max_rows]:
        if not isinstance(rec, Mapping):
            continue
        note = rec.get("note") or rec.get("comment")
        if isinstance(note, str) and note.strip():
            ticker = _safe_str(rec.get("ticker"), "-")
            notes_section.append(f"- **{ticker}**: {note}")
    if notes_section:
        lines.append("")
        lines.append("## 详细备注")
        lines.append("")
        lines.extend(notes_section)
    return "\n".join(lines)


def _truncate_for_channel(body: str, channel: PushChannel) -> tuple[str, bool]:
    """按通道限制截断消息 — 返回 ``(body, truncated)``。"""
    if not body:
        return body, False
    limit: int | None
    if channel is PushChannel.WECOM:
        limit = MAX_WECOM_CONTENT
    elif channel is PushChannel.DINGTALK:
        limit = MAX_DINGTALK_CONTENT
    else:
        return body, False  # EMAIL / WEBHOOK 无强限制
    encoded = body.encode("utf-8")
    if len(encoded) <= limit:
        return body, False
    # 保守按字符数截断, 留出 truncation 提示空间
    char_limit = max(64, (limit - 64) // 4)  # 简单按 4 字节/字符估算
    truncated_body = body[:char_limit] + "\n\n_... (内容已截断, 完整内容请查看 JSON 报告)_"
    return truncated_body, True


# ---------------------------------------------------------------------------
# 通道实现
# ---------------------------------------------------------------------------


def _send_email(
    config: PushConfig,
    payload: PushPayload,
    smtp_send_fn: SmtpSendFn,
) -> None:
    """邮件发送 (SMTP) — 抛异常表示失败, 由 send_push 统一捕获重试。"""
    if config.email is None:
        raise RuntimeError("EMAIL 通道未配置 email 子对象")
    config.email.validate()

    msg = MIMEMultipart()
    msg["From"] = config.email.smtp_user
    msg["To"] = config.email.to_addr
    msg["Subject"] = payload.subject
    msg.attach(MIMEText(payload.markdown_body, "plain", "utf-8"))

    if config.include_pdf and payload.pdf_path and payload.pdf_path.exists():
        try:
            pdf_bytes = payload.pdf_path.read_bytes()
            attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
            attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=payload.pdf_path.name,
            )
            msg.attach(attachment)
        except OSError as exc:
            logger.warning("[Push] PDF 附件读取失败, 继续发送纯文本: %s", exc)

    smtp_send_fn(config.email, msg)


def _send_wecom(
    config: PushConfig,
    payload: PushPayload,
    http_post_fn: HttpPostFn,
) -> None:
    """企微机器人 Webhook — POST markdown 消息。"""
    body, _ = _truncate_for_channel(payload.markdown_body, PushChannel.WECOM)
    request_body = {"msgtype": "markdown", "markdown": {"content": body}}
    status, text = http_post_fn(
        config.target,
        headers={},
        body=request_body,
        timeout=config.timeout,
    )
    if status != 200:
        raise RuntimeError(f"WeCom HTTP {status}: {text[:200]}")


def _send_dingtalk(
    config: PushConfig,
    payload: PushPayload,
    http_post_fn: HttpPostFn,
) -> None:
    """钉钉机器人 Webhook — POST markdown 消息。"""
    body, _ = _truncate_for_channel(payload.markdown_body, PushChannel.DINGTALK)
    request_body = {"msgtype": "markdown", "markdown": {"title": payload.subject, "text": body}}
    status, text = http_post_fn(
        config.target,
        headers={},
        body=request_body,
        timeout=config.timeout,
    )
    if status != 200:
        raise RuntimeError(f"DingTalk HTTP {status}: {text[:200]}")


def _send_generic_webhook(
    config: PushConfig,
    payload: PushPayload,
    http_post_fn: HttpPostFn,
) -> None:
    """通用 Webhook — POST 完整 JSON 载荷。"""
    request_body = {
        "subject": payload.subject,
        "markdown": payload.markdown_body,
        "data": payload.json_body,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    status, text = http_post_fn(
        config.target,
        headers={},
        body=request_body,
        timeout=config.timeout,
    )
    if status not in (200, 201, 202, 204):
        raise RuntimeError(f"Webhook HTTP {status}: {text[:200]}")


# ---------------------------------------------------------------------------
# 公共 API: 发送 + 配置加载
# ---------------------------------------------------------------------------


def send_push(
    config: PushConfig,
    report_data: dict[str, Any],
    pdf_path: Path | None = None,
    *,
    smtp_send_fn: SmtpSendFn | None = None,
    http_post_fn: HttpPostFn | None = None,
) -> PushResult:
    """发送一条推送 — 返回结果对象, 不抛异常。

    Args:
        config: 推送配置 (单通道)。
        report_data: 报告数据 (dict) — 用于渲染正文。
        pdf_path: 可选 PDF 附件路径 (EMAIL 通道且 ``include_pdf=True`` 时使用)。
        smtp_send_fn: SMTP 注入点 (测试用), 默认 ``_default_smtp_send``。
        http_post_fn: HTTP 注入点 (测试用), 默认 ``_default_http_post``。

    Returns:
        :class:`PushResult` — ``success`` 字段标识最终是否成功。
        重试耗尽 / 异常 → ``success=False, error=<msg>, attempts=MAX_RETRIES``。
    """
    if not config.enabled:
        return PushResult(
            channel=config.channel,
            target=config.target,
            success=True,  # 视为"未启用即成功"
            attempts=0,
        )

    smtp_fn = smtp_send_fn or _default_smtp_send
    http_fn = http_post_fn or _default_http_post

    start = time.monotonic()
    last_error: str | None = None

    # 渲染正文 (一次性, 避免每次重试都重算)
    # WeCom / DingTalk 通道: 用较大 max_rows (200) 让正文接近真实报告密度, 触发截断逻辑
    is_short_channel = config.channel in (PushChannel.WECOM, PushChannel.DINGTALK)
    render_max_rows = 200 if is_short_channel else 10
    try:
        markdown_body = format_report_markdown(report_data, max_rows=render_max_rows)
    except Exception as exc:  # pragma: no cover - 渲染失败兜底
        markdown_body = f"AI 选股日报 (渲染失败: {exc})"
        logger.warning("[Push] 报告渲染失败, 使用兜底文本: %s", exc)

    date_str = _safe_str(report_data.get("date"), datetime.now().strftime("%Y%m%d"))
    subject = config.subject_template.format(date=date_str)

    payload = PushPayload(
        subject=subject,
        markdown_body=markdown_body,
        json_body=dict(report_data) if isinstance(report_data, Mapping) else {},
        pdf_path=pdf_path,
    )

    truncated = False
    if config.channel in (PushChannel.WECOM, PushChannel.DINGTALK):
        payload.markdown_body, truncated = _truncate_for_channel(payload.markdown_body, config.channel)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if config.channel is PushChannel.EMAIL:
                _send_email(config, payload, smtp_fn)
            elif config.channel is PushChannel.WECOM:
                _send_wecom(config, payload, http_fn)
            elif config.channel is PushChannel.DINGTALK:
                _send_dingtalk(config, payload, http_fn)
            elif config.channel is PushChannel.GENERIC_WEBHOOK:
                _send_generic_webhook(config, payload, http_fn)
            else:
                raise RuntimeError(f"未知通道: {config.channel}")

            duration_ms = (time.monotonic() - start) * 1000
            return PushResult(
                channel=config.channel,
                target=config.target,
                success=True,
                attempts=attempt,
                duration_ms=duration_ms,
                truncated=truncated,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "[Push] %s 推送失败 (attempt=%d/%d): %s",
                config.channel.value,
                attempt,
                MAX_RETRIES,
                last_error,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))

    duration_ms = (time.monotonic() - start) * 1000
    return PushResult(
        channel=config.channel,
        target=config.target,
        success=False,
        attempts=MAX_RETRIES,
        error=last_error,
        duration_ms=duration_ms,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# 配置文件加载
# ---------------------------------------------------------------------------


def _coerce_bool(value: Any, default: bool = False) -> bool:
    """宽容 bool 解析 — 支持 1/0/true/false/yes/no/on/off。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return default


def _parse_channel(value: Any) -> PushChannel:
    """字符串 → PushChannel 枚举 (宽容大小写)。"""
    if isinstance(value, PushChannel):
        return value
    if not value:
        raise ValueError("channel 不能为空")
    s = str(value).strip().lower()
    for member in PushChannel:
        if member.value == s:
            return member
    raise ValueError(f"未知 channel: {value!r} (支持: {[m.value for m in PushChannel]})")


def _config_from_dict(raw: Mapping[str, Any]) -> PushConfig:
    """从单条 ``{channel, target, ...}`` dict 构造 PushConfig。"""
    channel = _parse_channel(raw.get("channel"))
    target = str(raw.get("target", "")).strip()
    if not target:
        raise ValueError(f"channel={channel.value} 的 target 不能为空")

    email_cfg: EmailConfig | None = None
    if channel is PushChannel.EMAIL:
        # 支持两种配置风格: 嵌套 ``email`` 子对象, 或顶层平铺 smtp_* 字段
        email_raw = raw.get("email")
        if not isinstance(email_raw, Mapping):
            email_raw = {}
        # 合并顶层 smtp_* 字段 (优先级: email.* > 顶层 *)
        merged_email: dict[str, Any] = dict(email_raw)
        for key in ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_password_env", "timeout"):
            if key in raw and key not in merged_email:
                merged_email[key] = raw[key]
        email_cfg = EmailConfig(
            to_addr=target,  # 默认 target 即收件人
            smtp_host=str(merged_email.get("smtp_host", "")).strip(),
            smtp_port=int(merged_email.get("smtp_port", 587) or 587),
            smtp_user=str(merged_email.get("smtp_user", "") or target).strip(),
            smtp_password=str(merged_email.get("smtp_password", "") or ""),
            smtp_password_env=str(merged_email.get("smtp_password_env", "") or ""),
            timeout=float(merged_email.get("timeout", 15.0) or 15.0),
        )
        # 允许在 email 子对象覆盖 to_addr
        if "to_addr" in merged_email and merged_email["to_addr"]:
            email_cfg.to_addr = str(merged_email["to_addr"]).strip()

    extra_raw = raw.get("extra") or {}
    if not isinstance(extra_raw, Mapping):
        extra_raw = {}

    return PushConfig(
        channel=channel,
        target=target,
        enabled=_coerce_bool(raw.get("enabled"), default=False),
        subject_template=str(raw.get("subject_template") or "AI 选股日报 · {date}"),
        include_pdf=_coerce_bool(raw.get("include_pdf"), default=True),
        email=email_cfg,
        timeout=float(raw.get("timeout", 15.0) or 15.0),
        extra=dict(extra_raw),
    )


def load_push_config(
    config_path: Path | str | None = None,
    *,
    only_enabled: bool = True,
) -> list[PushConfig]:
    """从 JSON 配置文件加载所有推送通道。

    Args:
        config_path: 配置文件路径, 默认 ``data/push_config.json``。
        only_enabled: True 时只返回 ``enabled=True`` 的通道。

    Returns:
        PushConfig 列表 — 配置文件不存在 / 解析失败时返回空列表 (优雅降级)。

    Raises:
        ValueError: 配置文件存在但 ``channels`` 字段非法。
    """
    path = Path(config_path) if config_path else DEFAULT_PUSH_CONFIG_PATH
    if not path.exists():
        logger.info("[Push] 配置文件不存在 (%s), 跳过加载", path)
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Push] 配置文件解析失败 (%s): %s", path, exc)
        return []

    if not isinstance(payload, Mapping):
        raise ValueError(f"推送配置根节点必须为 JSON object, 实际: {type(payload).__name__}")
    channels_raw = payload.get("channels")
    if not isinstance(channels_raw, list):
        raise ValueError("推送配置必须包含 'channels' 数组")

    configs: list[PushConfig] = []
    for idx, item in enumerate(channels_raw):
        if not isinstance(item, Mapping):
            logger.warning("[Push] 跳过非 dict 通道 (index=%d)", idx)
            continue
        try:
            cfg = _config_from_dict(item)
        except (ValueError, TypeError) as exc:
            logger.warning("[Push] 跳过非法通道 (index=%d): %s", idx, exc)
            continue
        if only_enabled and not cfg.enabled:
            continue
        configs.append(cfg)
    return configs


def build_default_config(
    *,
    wecom_url: str = "",
    dingtalk_url: str = "",
    email_to: str = "",
    enabled_channels: Sequence[str] = (),
) -> dict[str, Any]:
    """构造一份默认配置 (供 ``--push-test --init`` 或测试使用)。

    Args:
        wecom_url: 企微 Webhook URL (空字符串表示不写入该通道)。
        dingtalk_url: 钉钉 Webhook URL。
        email_to: 邮件收件人地址。
        enabled_channels: 需要 enabled=True 的通道名列表
            (e.g. ``["wecom", "email"]``); 其余通道 enabled=False。

    Returns:
        dict — 可直接 ``json.dump`` 写入配置文件。
    """
    enabled_set = {s.strip().lower() for s in enabled_channels if s}
    channels: list[dict[str, Any]] = []

    if wecom_url:
        channels.append(
            {
                "channel": "wecom",
                "target": wecom_url,
                "enabled": "wecom" in enabled_set,
            }
        )
    if dingtalk_url:
        channels.append(
            {
                "channel": "dingtalk",
                "target": dingtalk_url,
                "enabled": "dingtalk" in enabled_set,
            }
        )
    if email_to:
        channels.append(
            {
                "channel": "email",
                "target": email_to,
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": email_to,
                "smtp_password_env": "SMTP_PASSWORD",
                "enabled": "email" in enabled_set,
            }
        )

    return {
        "schema_version": PUSH_SCHEMA_VERSION,
        "push_version": PUSH_VERSION,
        "channels": channels,
    }
