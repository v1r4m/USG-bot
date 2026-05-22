"""하양이 봇 본체."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from hayangi.config import Settings

log = logging.getLogger(__name__)

#: setup_hook 단계에서 자동으로 로드할 확장(코그) 목록.
INITIAL_EXTENSIONS: tuple[str, ...] = (
    "hayangi.cogs.general",
    "hayangi.cogs.ctf",
)


class HayangiBot(commands.Bot):
    """USG CTF 디스코드 봇 '하양이'."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        super().__init__(
            # 슬래시 커맨드만 사용하므로 접두사 명령은 멘션으로만 받습니다.
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
        )

    async def setup_hook(self) -> None:
        """봇이 로그인한 직후, 게이트웨이 연결 전에 한 번 호출됩니다."""
        self.tree.error(self.on_app_command_error)

        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)
            log.info("확장 로드 완료: %s", extension)

        await self._sync_commands()

    async def _sync_commands(self) -> None:
        """슬래시 커맨드를 디스코드에 동기화합니다.

        길드 동기화에 실패하더라도 봇은 계속 실행되며 전역 동기화로 대체합니다.
        """
        if self.settings.guild_id is not None:
            guild = discord.Object(id=self.settings.guild_id)
            # 전역 커맨드를 개발 길드로 복사해 즉시 반영합니다.
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.Forbidden:
                log.error(
                    "길드(%s) 커맨드 동기화 실패 (Missing Access) — 봇이 해당 "
                    "서버에 없거나 'applications.commands' 범위로 초대되지 "
                    "않았을 수 있어요. 전역 동기화로 대체합니다.",
                    self.settings.guild_id,
                )
            else:
                log.info(
                    "길드(%s)에 슬래시 커맨드 %d개 동기화 완료",
                    self.settings.guild_id,
                    len(synced),
                )
                return

        synced = await self.tree.sync()
        log.info(
            "전역 슬래시 커맨드 %d개 동기화 완료 (모든 서버 반영까지 최대 1시간 소요)",
            len(synced),
        )

    async def on_ready(self) -> None:
        log.info(
            "로그인 성공: %s (ID: %s)",
            self.user,
            getattr(self.user, "id", "?"),
        )
        if self.guilds:
            for guild in self.guilds:
                log.info("참여 중인 서버: %s (ID: %s)", guild.name, guild.id)
        else:
            log.warning("참여 중인 서버가 없습니다 — 봇을 서버에 초대했는지 확인하세요.")
        log.info("하양이 준비 완료 ~_~")

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """슬래시 커맨드 실행 중 발생한 예외를 처리합니다."""
        if isinstance(error, app_commands.MissingPermissions):
            message = "🚫 이 명령은 채널·역할 관리 권한이 있는 사람만 쓸 수 있어요."
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "🚫 이 명령은 서버 안에서만 쓸 수 있어요."
        elif isinstance(error, app_commands.CheckFailure):
            message = "🚫 이 명령을 실행할 권한이 없어요."
        elif isinstance(error, app_commands.CommandInvokeError) and isinstance(
            error.original, discord.Forbidden
        ):
            log.error("하양이 권한 부족", exc_info=error.original)
            message = (
                "⚠️ 하양이의 권한이 부족해요. **역할 관리·채널 관리** 권한이 있는지, "
                "하양이의 역할이 충분히 위에 있는지 확인해 주세요."
            )
        else:
            log.error("처리되지 않은 슬래시 커맨드 오류: %s", error, exc_info=error)
            message = "⚠️ 명령어를 처리하는 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            log.warning("오류 메시지를 전송하지 못했습니다.", exc_info=True)
