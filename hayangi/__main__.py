"""하양이 실행 진입점: `python -m hayangi`."""

from __future__ import annotations

import asyncio
import logging
import sys

from hayangi.bot import HayangiBot
from hayangi.config import Settings
from hayangi.logger import setup_logging


async def _run(settings: Settings) -> None:
    bot = HayangiBot(settings)
    async with bot:
        await bot.start(settings.token)


def main() -> None:
    try:
        settings = Settings.load()
    except RuntimeError as exc:
        print(f"[설정 오류] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    setup_logging(settings.log_level)
    log = logging.getLogger("hayangi")
    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        log.info("하양이를 종료합니다. 안녕히 ~_~")


if __name__ == "__main__":
    main()
