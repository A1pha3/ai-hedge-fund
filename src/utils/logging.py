"""统一日志配置模块"""

import logging
import logging.config
from pathlib import Path
from typing import Optional


def setup_logging(log_dir: Path = Path("logs"), level: str = "INFO", format: Optional[str] = None):
    """配置日志系统

    配置三个日志处理器：
    1. console: 输出到控制台
    2. file: 输出到文件（轮转）
    3. error_file: 只记录 ERROR 及以上级别的日志

    Args:
        log_dir: 日志目录
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        format: 日志格式字符串
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志格式：时间 | 级别 | 模块:函数:行号 | 消息
    log_format = format or ("%(asctime)s | %(levelname)-8s | " "%(name)s:%(funcName)s:%(lineno)d | %(message)s")

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"standard": {"format": log_format, "datefmt": "%Y-%m-%d %H:%M:%S"}, "detailed": {"format": log_format, "datefmt": "%Y-%m-%d %H:%M:%S.%f"}},
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "standard", "stream": "ext://sys.stdout", "level": level},
                "file": {"class": "logging.handlers.RotatingFileHandler", "filename": log_dir / "app.log", "formatter": "detailed", "level": level, "maxBytes": 10 * 1024 * 1024, "backupCount": 5},  # 10MB
                "error_file": {"class": "logging.handlers.RotatingFileHandler", "filename": log_dir / "error.log", "formatter": "detailed", "level": "ERROR", "maxBytes": 10 * 1024 * 1024, "backupCount": 5},  # 10MB
            },
            "root": {"handlers": ["console", "file", "error_file"], "level": level},
        }
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取日志记录器

    Args:
        name: 日志记录器名称，通常使用 __name__

    Returns:
        logging.Logger: 日志记录器实例
    """
    return logging.getLogger(name)
