"""기본 명령어 코그: /ping, /help."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from hayangi.bot import HayangiBot

#: 하양이를 상징하는 흰색 계열 임베드 색상.
EMBED_COLOR = discord.Color.from_rgb(240, 240, 240)


class General(commands.Cog):
    """봇 상태 확인과 도움말을 제공하는 기본 명령어 모음."""

    def __init__(self, bot: HayangiBot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="하양이가 살아있는지 확인합니다.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🤍 퐁! 응답 지연: `{latency_ms}ms`",
            ephemeral=True,
        )

    @app_commands.command(name="help", description="하양이가 할 수 있는 일을 알려줍니다.")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🤍 하양이 도움말",
            description=(
                "USG CTF 디스코드 봇 **하양이**예요.\n"
                "현재 사용할 수 있는 명령어 목록입니다."
            ),
            color=EMBED_COLOR,
        )
        for command in sorted(self.bot.tree.get_commands(), key=lambda c: c.name):
            if isinstance(command, app_commands.Group):
                # 그룹은 하위 명령어를 펼쳐서 보여줍니다.
                subcommands = sorted(command.commands, key=lambda c: c.name)
                value = "\n".join(
                    f"`/{command.name} {sub.name}` — {sub.description}"
                    for sub in subcommands
                )
            else:
                value = command.description or "(설명 없음)"
            embed.add_field(name=f"/{command.name}", value=value, inline=False)
        embed.set_footer(text="하양이 ~_~ · USG CTF 디스코드 봇")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: HayangiBot) -> None:
    """확장 진입점: General 코그를 봇에 등록합니다."""
    await bot.add_cog(General(bot))
