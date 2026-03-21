"""
Module: app/core/logger.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 日志初始化：统一日志级别与输出格式。

import logging


def setup_logging() -> None:
    # 配置全局日志格式与默认级别。
    """Public API `setup_logging` used by other modules or route handlers."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    # 可选桥接未启动时会产生大量探活日志，这里下调第三方 HTTP 日志级别。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
