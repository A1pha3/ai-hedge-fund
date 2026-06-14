"""P2-3 每日选股结果推送 — 邮件 / 企微 / 钉钉 / 通用 Webhook。"""

from .push import (
    build_default_config,
    DEFAULT_PUSH_CONFIG_PATH,
    EmailConfig,
    format_report_markdown,
    load_push_config,
    MAX_DINGTALK_CONTENT,
    MAX_WECOM_CONTENT,
    PUSH_SCHEMA_VERSION,
    PUSH_VERSION,
    PushChannel,
    PushConfig,
    PushPayload,
    PushResult,
    send_push,
)
from .weekly_report import (
    generate_weekly_report,
    push_weekly_report,
)

__all__ = [
    "DEFAULT_PUSH_CONFIG_PATH",
    "MAX_WECOM_CONTENT",
    "MAX_DINGTALK_CONTENT",
    "PUSH_SCHEMA_VERSION",
    "PUSH_VERSION",
    "EmailConfig",
    "PushChannel",
    "PushConfig",
    "PushPayload",
    "PushResult",
    "build_default_config",
    "format_report_markdown",
    "load_push_config",
    "send_push",
    "generate_weekly_report",
    "push_weekly_report",
]
