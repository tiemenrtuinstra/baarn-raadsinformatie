#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging configuratie voor Baarn Politiek MCP Server.

BELANGRIJK: MCP servers communiceren via stdio (stdin/stdout).
Daarom MOET alle logging naar een bestand gaan, NIET naar stdout/stderr.
"""

import logging
import os
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler


def get_log_dir() -> Path:
    """Get the logs directory, create if not exists."""
    base_dir = Path(__file__).parent.parent
    log_dir = base_dir / 'logs'
    log_dir.mkdir(exist_ok=True)
    return log_dir


def get_logger(name: str = 'baarn-politiek') -> logging.Logger:
    """
    Get a configured logger that writes to file.

    Args:
        name: Logger name

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Voorkom duplicate handlers
    if logger.handlers:
        return logger

    # Log level from environment
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # File handler met rotation
    log_file = get_log_dir() / f'{name}.log'
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )

    # Format
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_mcp_logger() -> logging.Logger:
    """
    Get logger specifically for MCP server.
    Ensures NO output goes to stdout/stderr.

    Returns:
        Configured logger for MCP server
    """
    logger = get_logger('mcp-server')

    # Extra check: remove any stream handlers
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)

    return logger


class LogContext:
    """Context manager for logging with context info."""

    def __init__(self, logger: logging.Logger, operation: str, **context):
        self.logger = logger
        self.operation = operation
        self.context = context
        self.start_time = None

    def __enter__(self):
        self.start_time = datetime.now()
        context_str = ' | '.join(f'{k}={v}' for k, v in self.context.items())
        self.logger.info(f'START {self.operation} | {context_str}')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()
        if exc_type:
            self.logger.error(f'FAIL {self.operation} | duration={duration:.2f}s | error={exc_val}')
        else:
            self.logger.info(f'END {self.operation} | duration={duration:.2f}s')
        return False


if __name__ == '__main__':
    # Test logging
    logger = get_logger('test')
    logger.info('Test log message')
    logger.warning('Test warning')
    logger.error('Test error')
    print(f'Log file: {get_log_dir() / "test.log"}')
