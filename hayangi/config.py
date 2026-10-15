"""환경 변수 기반 봇 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 프로젝트 루트의 .env 파일을 환경 변수로 읽어옵니다.
load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    """봇 실행에 필요한 설정값 묶음."""

    token: str
    guild_id: int | None
    log_level: str
    data_dir: str
    ctfd_poll_minutes: int

    @classmethod
    def load(cls) -> Settings:
        """환경 변수에서 설정을 읽어 Settings 인스턴스를 만듭니다.

        Raises:
            RuntimeError: 필수 값(DISCORD_TOKEN)이 없거나 값이 잘못된 경우.
        """
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "DISCORD_TOKEN 환경 변수가 설정되지 않았습니다. "
                ".env.example 를 복사해 .env 파일을 만들고 토큰을 채워 주세요."
            )

        guild_raw = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_raw and not guild_raw.isdigit():
            raise RuntimeError(
                f"DISCORD_GUILD_ID 값이 올바르지 않습니다: {guild_raw!r} "
                "(서버 ID는 숫자여야 합니다)."
            )
        guild_id = int(guild_raw) if guild_raw else None

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"

        data_dir = os.getenv("DATA_DIR", "").strip() or "data"

        poll_raw = os.getenv("CTFD_POLL_MINUTES", "").strip() or "5"
        if not poll_raw.isdigit() or int(poll_raw) < 1:
            raise RuntimeError(
                f"CTFD_POLL_MINUTES 값이 올바르지 않습니다: {poll_raw!r} (1 이상의 정수)."
            )

        return cls(
            token=token,
            guild_id=guild_id,
            log_level=log_level,
            data_dir=data_dir,
            ctfd_poll_minutes=int(poll_raw),
        )
