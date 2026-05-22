"""로깅 설정."""

from __future__ import annotations

import logging
import sys

_FORMAT = "[{asctime}] [{levelname:<8}] {name}: {message}"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """루트 로거를 표준 출력으로 향하도록 구성합니다.

    discord.py 내부 로그도 루트 로거로 전파되므로 함께 출력됩니다.

    Args:
        level: 로그 레벨 이름(DEBUG/INFO/WARNING/ERROR). 알 수 없는 값이면 INFO.
    """
    level_value = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT, style="{"))

    root = logging.getLogger()
    root.setLevel(level_value)
    root.handlers.clear()
    root.addHandler(handler)
