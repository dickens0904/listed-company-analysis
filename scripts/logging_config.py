# -*- coding: utf-8 -*-
"""
结构化日志配置 — 替代项目中散落的 print()

用法:
    from scripts.logging_config import get_logger
    logger = get_logger(__name__)
    logger.warning("dim_failed", dim=dim, error=str(e))
"""
import logging
import sys

_CONFIGURED = False


def get_logger(name: str = "company-analysis") -> logging.Logger:
    """获取配置好的 logger。首次调用自动配置。"""
    global _CONFIGURED
    if not _CONFIGURED:
        _configure()
        _CONFIGURED = True
    return logging.getLogger(name)


def _configure() -> None:
    """一次性配置：INFO 级别，统一格式。"""
    root = logging.getLogger()
    if root.handlers:
        return  # 已有配置，不覆盖

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
