"""문제(챌린지) 관리 코그.

명령어: ``/chal add · solve · unsolve · list``

문제는 CTF 카테고리 안의 ``#🧩-<카테고리>`` 채널에 스레드로 만들어집니다.
자세한 규칙은 :mod:`hayangi.challenges` 모듈 문서를 참고하세요.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from hayangi import challenges as chal

if TYPE_CHECKING:
    from hayangi.bot import HayangiBot

log = logging.getLogger(__name__)

#: CTF 밖에서 명령을 실행했을 때의 안내 문구.
NOT_IN_CTF = "❌ CTF 카테고리 안의 채널에서 실행해 주세요."
NOT_IN_THREAD = "❌ 문제 스레드 안에서 실행해 주세요."


class Challenges(commands.Cog):
    """CTF 문제 스레드의 생성과 풀이 상태를 관리하는 코그."""

    chal = app_commands.Group(
        name="chal",
        description="CTF 문제 관리",
        guild_only=True,
    )

    def __init__(self, bot: HayangiBot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /chal add
    # ------------------------------------------------------------------
    @chal.command(name="add", description="현재 CTF에 문제 스레드를 만듭니다.")
    @app_commands.describe(
        name="문제 이름",
        category="문제 카테고리 (예: pwn, web, rev, crypto)",
        description="(선택) 문제 설명이나 메모",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        name: str,
        category: str,
        description: str | None = None,
    ) -> None:
        info = chal.ctf_of(interaction.channel)
        if info is None:
            await interaction.response.send_message(NOT_IN_CTF, ephemeral=True)
            return
        if info.archived:
            await interaction.response.send_message(
                f"🗄️ **{info.name}** 은 보관된 CTF라 문제를 추가할 수 없어요.", ephemeral=True
            )
            return

        name = " ".join(name.split())
        category = " ".join(category.split())
        if not name or len(name) > chal.CHALLENGE_NAME_MAX_LEN:
            await interaction.response.send_message(
                f"❌ 문제 이름은 1~{chal.CHALLENGE_NAME_MAX_LEN}자로 지어 주세요.", ephemeral=True
            )
            return
        if not category or len(category) > chal.CATEGORY_NAME_MAX_LEN:
            await interaction.response.send_message(
                f"❌ 카테고리 이름은 1~{chal.CATEGORY_NAME_MAX_LEN}자로 지어 주세요.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        reason = f"하양이: {interaction.user} 님이 문제 추가"
        channel = await chal.get_or_create_category_channel(info, category, reason=reason)

        existing = await chal.find_challenge_thread(channel, name)
        if existing is not None:
            await interaction.followup.send(f"이미 있는 문제예요: {existing.mention}")
            return

        thread = await chal.create_challenge_thread(
            channel,
            name,
            chal.challenge_embed(name, category, description=description),
            reason=reason,
        )
        log.info(
            "문제 추가: '%s' / %s / %s (요청자: %s)", info.name, category, name, interaction.user
        )
        await interaction.followup.send(f"✅ 문제 스레드를 만들었어요: {thread.mention}")

    @add.autocomplete("category")
    async def add_category_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        info = chal.ctf_of(interaction.channel)
        if info is None:
            return []
        current_cf = current.casefold()
        return [
            app_commands.Choice(name=name, value=name)
            for name in sorted(chal.category_channels(info), key=str.casefold)
            if current_cf in name.casefold()
        ][:25]

    # ------------------------------------------------------------------
    # /chal solve · unsolve
    # ------------------------------------------------------------------
    @chal.command(name="solve", description="이 문제를 해결했다고 표시합니다.")
    async def solve(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, solved=True)

    @chal.command(name="unsolve", description="이 문제의 해결 표시를 취소합니다.")
    async def unsolve(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, solved=False)

    async def _toggle(self, interaction: discord.Interaction, *, solved: bool) -> None:
        thread = interaction.channel
        if not chal.is_challenge_thread(thread):
            await interaction.response.send_message(NOT_IN_THREAD, ephemeral=True)
            return
        assert isinstance(thread, discord.Thread)
        if chal.is_solved(thread) == solved:
            await interaction.response.send_message(
                "이미 해결된 문제예요." if solved else "아직 해결되지 않은 문제예요.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        name = chal.challenge_name(thread)
        action = "해결" if solved else "해결 취소"
        await chal.set_solved(
            thread, solved, reason=f"하양이: {interaction.user} 님이 문제 {action}"
        )
        log.info("문제 %s: '%s' (요청자: %s)", action, name, interaction.user)

        if not solved:
            await interaction.followup.send(f"↩️ **{name}** 의 해결 표시를 취소했어요.")
            return

        await interaction.followup.send(
            embed=discord.Embed(
                title=f"🎉 {name} 해결!",
                description=f"{interaction.user.mention} 님이 해결했어요.",
                color=chal.SOLVED_COLOR,
            )
        )
        info = chal.ctf_of(thread)
        announce = chal.announce_channel(info) if info is not None else None
        if announce is not None:
            await announce.send(
                f"🎉 {interaction.user.mention} 님이 {thread.mention} 를 해결했어요!"
            )

    # ------------------------------------------------------------------
    # /chal list
    # ------------------------------------------------------------------
    @chal.command(name="list", description="현재 CTF의 문제 목록과 풀이 현황을 보여줍니다.")
    async def list_challenges(self, interaction: discord.Interaction) -> None:
        info = chal.ctf_of(interaction.channel)
        if info is None:
            await interaction.response.send_message(NOT_IN_CTF, ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        embed = discord.Embed(title=f"🧩 {info.name} 문제 목록", color=chal.EMBED_COLOR)
        total = solved = 0
        for category, channel in sorted(
            chal.category_channels(info).items(), key=lambda kv: kv[0].casefold()
        ):
            threads = sorted(
                await chal.challenge_threads(channel),
                key=lambda t: chal.challenge_name(t).casefold(),
            )
            if not threads:
                continue
            done = sum(chal.is_solved(t) for t in threads)
            total += len(threads)
            solved += done

            lines: list[str] = []
            for thread in threads:
                line = f"{'✅' if chal.is_solved(thread) else '▫️'} {thread.mention}"
                if sum(len(x) + 1 for x in lines) + len(line) > 1000:
                    lines.append("…")
                    break
                lines.append(line)
            if len(embed.fields) < 25:
                embed.add_field(
                    name=f"{category} ({done}/{len(threads)})",
                    value="\n".join(lines),
                    inline=False,
                )

        if total == 0:
            embed.description = "아직 문제가 없어요. `/chal add` 로 추가해 보세요!"
        else:
            embed.description = f"해결 **{solved} / {total}**"
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: HayangiBot) -> None:
    """확장 진입점: 문제 관리 코그를 봇에 등록합니다."""
    await bot.add_cog(Challenges(bot))
