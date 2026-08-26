"""
日志配置
=======
基于 loguru 的统一日志管理。
支持控制台彩色输出和文件轮转。
"""

import sys
from loguru import logger


def setup_logger(level: str = "INFO", log_file: str = "megoo.log"):
    """
    初始化日志配置

    Args:
        level: 日志级别 (DEBUG / INFO / WARNING / ERROR)
        log_file: 日志文件路径
    """
    # 移除默认handler
    logger.remove()

    # 控制台输出（彩色）
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
        level=level,
        colorize=True,
    )

    # 文件输出（详细格式，带轮转）
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
               "{name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
    )

    logger.info(f"日志系统初始化完成，级别: {level}")
    return logger


# 默认初始化（INFO级别）
setup_logger()
