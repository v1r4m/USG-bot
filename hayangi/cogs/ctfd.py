"""CTFd 연동 코그.

명령어: ``/ctfd link · unlink · sync · status``

연동된 CTF 는 주기적으로(기본 5분) CTFd 를 확인해서

* 새로 열린 문제 → 문제 스레드 생성 + 공지
* 우리 팀이 푼 문제 → 해결 표시 + 공지

를 자동으로 처리합니다. 보관된 CTF 는 확인하지 않습니다.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from hayangi import challenges as chal
from hayangi import ctf as ctflib
from hayangi.ctfd import Challenge, CTFdClient, CTFdError, normalize_url
from hayangi.store import CTFdLink

if TYPE_CHECKING:
    from hayangi.bot import HayangiBot

log = logging.getLogger(__name__)

SYNC_REASON = "하양이: CTFd 동기화"


@dataclass(slots=True)
class SyncResult:
    """동기화 1회에서 새로 생긴 변화."""

    created: list[discord.Thread] = field(default_factory=list)
    solved: list[discord.Thread] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.created or self.solved)


class CTFdSync(commands.Cog, name="CTFd"):
    """CTFd 대회의 문제를 가져와 스레드로 만들고 풀이 상태를 반영하는 코그."""

    ctfd = app_commands.Group(
        name="ctfd",
        description="CTFd 대회 연동",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True),
    )

    def __init__(self, bot: HayangiBot) -> None:
        self.bot = bot
        self.store = bot.store
        # 같은 CTF 를 폴링과 수동 동기화가 동시에 건드려 스레드가 중복 생성되지 않게.
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        # 동기화가 실패 중인 CTF — 실패/복구 시점에만 공지하기 위해 기억합니다.
        self._failing: set[int] = set()

    async def cog_load(self) -> None:
        self.poll.change_interval(minutes=self.bot.settings.ctfd_poll_minutes)
        self.poll.start()

    async def cog_unload(self) -> None:
        self.poll.cancel()

    # ------------------------------------------------------------------
    # 동기화 로직
    # ------------------------------------------------------------------
    def _client(self, link: CTFdLink) -> CTFdClient:
        return CTFdClient(self.bot.web, link.url, link.credential)

    async def link(self, info: ctflib.CTFInfo, url: str, credential: str) -> SyncResult:
        """CTF 를 CTFd 와 연동하고 곧바로 첫 동기화를 합니다.

        Raises:
            CTFdError: 주소가 잘못됐거나 인증에 실패한 경우 (이때는 저장하지 않음).
        """
        url = normalize_url(url)
        credential = credential.strip()
        # 저장 전에 실제로 문제 목록을 읽을 수 있는지 확인합니다.
        await CTFdClient(self.bot.web, url, credential).challenges()

        previous = self.store.get(info.category.id)
        link = CTFdLink(guild_id=info.category.guild.id, url=url, credential=credential)
        if previous is not None and previous.url == url:
            # 같은 대회에 토큰만 바꿔 다시 연동하면 이미 만든 스레드를 그대로 이어 씁니다.
            link.threads, link.solved = previous.threads, previous.solved
        self.store.set(info.category.id, link)
        self._failing.discard(info.category.id)
        log.info("CTFd 연동: '%s' -> %s", info.name, url)
        return await self.sync(info, link)

    async def sync(self, info: ctflib.CTFInfo, link: CTFdLink) -> SyncResult:
        """CTFd 문제 목록을 Discord 에 반영합니다."""
        async with self._locks[info.category.id]:
            client = self._client(link)
            challenges = await client.challenges()
            guild = info.category.guild
            result = SyncResult()

            for challenge in challenges:
                thread_id = link.threads.get(challenge.id)
                if thread_id is None:
                    thread = await self._ensure_thread(info, client, challenge, result)
                    link.threads[challenge.id] = thread.id
                    self.store.save()
                elif challenge.solved and challenge.id not in link.solved:
                    thread = await self._get_thread(guild, thread_id)
                else:
                    continue

                if not challenge.solved or challenge.id in link.solved:
                    continue
                link.solved.add(challenge.id)
                self.store.save()
                # 누군가 스레드를 지웠다면 다시 만들지 않습니다.
                if thread is None:
                    continue
                if await chal.set_solved(thread, True, reason=SYNC_REASON):
                    await thread.send(
                        embed=discord.Embed(
                            title=f"🎉 {chal.challenge_name(thread)} 해결!",
                            description="CTFd에서 우리 팀의 풀이가 확인됐어요.",
                            color=chal.SOLVED_COLOR,
                        )
                    )
                    result.solved.append(thread)

            if result:
                log.info(
                    "CTFd 동기화 '%s': 새 문제 %d개, 새 해결 %d개",
                    info.name,
                    len(result.created),
                    len(result.solved),
                )
            return result

    async def _ensure_thread(
        self,
        info: ctflib.CTFInfo,
        client: CTFdClient,
        challenge: Challenge,
        result: SyncResult,
    ) -> discord.Thread:
        """CTFd 문제에 대응하는 스레드를 찾거나 만듭니다.

        `/chal add` 로 손수 만든 같은 이름의 스레드가 있으면 그것을 이어 씁니다.
        """
        channel = await chal.get_or_create_category_channel(
            info, challenge.category[: chal.CATEGORY_NAME_MAX_LEN], reason=SYNC_REASON
        )
        existing = await chal.find_challenge_thread(channel, challenge.name)
        if existing is not None:
            return existing

        try:
            detail = await client.challenge(challenge.id)
        except CTFdError as exc:
            log.warning("문제 상세를 가져오지 못했어요 (#%d): %s", challenge.id, exc)
            embed = chal.challenge_embed(
                challenge.name, challenge.category, value=challenge.value, source="CTFd"
            )
        else:
            embed = chal.challenge_embed(
                challenge.name,
                challenge.category,
                value=detail.value,
                description=detail.description,
                connection_info=detail.connection_info,
                files=detail.files,
                tags=detail.tags,
                source=f"CTFd #{challenge.id} · 해결하면 /chal solve",
            )
        thread = await chal.create_challenge_thread(
            channel, challenge.name, embed, reason=SYNC_REASON
        )
        result.created.append(thread)
        return thread

    @staticmethod
    async def _get_thread(guild: discord.Guild, thread_id: int) -> discord.Thread | None:
        thread = guild.get_thread(thread_id)
        if thread is not None:
            return thread
        try:
            channel = await guild.fetch_channel(thread_id)
        except (discord.NotFound, discord.Forbidden):
            return None
        return channel if isinstance(channel, discord.Thread) else None

    @staticmethod
    async def _announce(info: ctflib.CTFInfo, result: SyncResult) -> None:
        """동기화 결과를 CTF 공지 채널에 알립니다."""
        channel = chal.announce_channel(info)
        if channel is None or not result:
            return
        embed = discord.Embed(title="🔄 CTFd 업데이트", color=chal.EMBED_COLOR)
        for title, threads in (("🆕 새 문제", result.created), ("🎉 해결", result.solved)):
            if not threads:
                continue
            lines: list[str] = []
            for thread in threads:
                if sum(len(x) + 1 for x in lines) > 950:
                    lines.append(f"… 외 {len(threads) - len(lines)}개")
                    break
                lines.append(f"• {thread.mention}")
            embed.add_field(name=f"{title} ({len(threads)})", value="\n".join(lines), inline=False)
        await channel.send(embed=embed)

    # ------------------------------------------------------------------
    # 주기적 폴링
    # ------------------------------------------------------------------
    @tasks.loop(minutes=5)
    async def poll(self) -> None:
        for category_id, link in self.store.items():
            guild = self.bot.get_guild(link.guild_id)
            if guild is None or guild.unavailable:
                continue
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                # 카테고리가 손으로 지워졌다면 연동도 정리합니다.
                log.info("카테고리(%s)가 사라져 CTFd 연동을 해제합니다.", category_id)
                self.store.remove(category_id)
                continue
            info = ctflib.resolve_ctf(category)
            if info is None or info.archived:
                continue

            try:
                result = await self.sync(info, link)
            except CTFdError as exc:
                log.warning("CTFd 동기화 실패 '%s': %s", info.name, exc)
                if category_id not in self._failing:
                    self._failing.add(category_id)
                    await self._notify(info, f"⚠️ CTFd 자동 동기화에 실패했어요: {exc}")
                continue
            except Exception:
                # 한 CTF 의 오류 때문에 폴링 루프 전체가 멈추지 않게 합니다.
                log.exception("CTFd 동기화 중 예기치 못한 오류 '%s'", info.name)
                continue

            if category_id in self._failing:
                self._failing.discard(category_id)
                await self._notify(info, "✅ CTFd 자동 동기화가 다시 정상 동작해요.")
            await self._announce(info, result)

    @poll.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    @staticmethod
    async def _notify(info: ctflib.CTFInfo, message: str) -> None:
        channel = chal.announce_channel(info)
        if channel is None:
            return
        try:
            await channel.send(message)
        except discord.HTTPException:
            log.warning("공지 전송 실패: '%s'", info.name, exc_info=True)

    # ------------------------------------------------------------------
    # 명령어
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve(interaction: discord.Interaction, name: str | None) -> ctflib.CTFInfo | None:
        """``name`` 이 있으면 그 CTF, 없으면 명령을 실행한 채널이 속한 CTF."""
        guild = interaction.guild
        assert guild is not None
        if name:
            return ctflib.find_ctf(guild, name)
        return chal.ctf_of(interaction.channel)

    @staticmethod
    def _not_found(name: str | None) -> str:
        if name:
            return f"❌ **{name}** CTF를 찾을 수 없어요."
        return "❌ CTF 이름을 지정하거나, CTF 카테고리 안의 채널에서 실행해 주세요."

    @ctfd.command(name="link", description="CTF를 CTFd 대회와 연동하고 문제를 가져옵니다.")
    @app_commands.describe(
        url="CTFd 대회 주소 (예: https://ctf.example.com)",
        token="CTFd API 토큰(ctfd_...) 또는 브라우저의 session 쿠키 값",
        ctf="연동할 CTF (비우면 현재 채널의 CTF)",
    )
    async def link_cmd(
        self,
        interaction: discord.Interaction,
        url: str,
        token: str,
        ctf: str | None = None,
    ) -> None:
        info = self._resolve(interaction, ctf)
        if info is None:
            await interaction.response.send_message(self._not_found(ctf), ephemeral=True)
            return
        if info.archived:
            await interaction.response.send_message(
                f"🗄️ **{info.name}** 은 보관된 CTF예요. 먼저 `/ctf unarchive` 해 주세요.",
                ephemeral=True,
            )
            return

        # 토큰이 노출되지 않도록 응답은 본인에게만 보입니다.
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            result = await self.link(info, url, token)
        except CTFdError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        link = self.store.get(info.category.id)
        assert link is not None
        await interaction.followup.send(
            f"🔗 **{info.name}** 을 {link.url} 와 연동했어요. "
            f"새 문제 {len(result.created)}개를 가져왔고, "
            f"{self.bot.settings.ctfd_poll_minutes}분마다 새 문제와 풀이를 확인할게요.",
            ephemeral=True,
        )
        await self._announce(info, result)

    @ctfd.command(
        name="unlink", description="CTFd 연동을 해제합니다 (만든 스레드는 그대로 남아요)."
    )
    @app_commands.describe(ctf="연동을 해제할 CTF (비우면 현재 채널의 CTF)")
    async def unlink_cmd(self, interaction: discord.Interaction, ctf: str | None = None) -> None:
        info = self._resolve(interaction, ctf)
        if info is None:
            await interaction.response.send_message(self._not_found(ctf), ephemeral=True)
            return
        if not self.store.remove(info.category.id):
            await interaction.response.send_message(
                f"**{info.name}** 은 CTFd와 연동되어 있지 않아요.", ephemeral=True
            )
            return
        self._failing.discard(info.category.id)
        log.info("CTFd 연동 해제: '%s' (요청자: %s)", info.name, interaction.user)
        await interaction.response.send_message(
            f"🔌 **{info.name}** 의 CTFd 연동을 해제하고 저장된 토큰을 지웠어요.", ephemeral=True
        )

    @ctfd.command(name="sync", description="CTFd에서 새 문제와 풀이 상태를 지금 바로 가져옵니다.")
    @app_commands.describe(ctf="동기화할 CTF (비우면 현재 채널의 CTF)")
    async def sync_cmd(self, interaction: discord.Interaction, ctf: str | None = None) -> None:
        info = self._resolve(interaction, ctf)
        if info is None:
            await interaction.response.send_message(self._not_found(ctf), ephemeral=True)
            return
        link = self.store.get(info.category.id)
        if link is None:
            await interaction.response.send_message(
                f"**{info.name}** 은 CTFd와 연동되어 있지 않아요. "
                "`/ctfd link` 로 먼저 연동해 주세요.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            result = await self.sync(info, link)
        except CTFdError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        self._failing.discard(info.category.id)
        await interaction.followup.send(
            f"🔄 동기화 완료 — 새 문제 {len(result.created)}개, 새 해결 {len(result.solved)}개.",
            ephemeral=True,
        )
        await self._announce(info, result)

    @ctfd.command(name="status", description="CTFd와 연동된 CTF 목록을 보여줍니다.")
    async def status_cmd(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        embed = discord.Embed(title="🔗 CTFd 연동 현황", color=chal.EMBED_COLOR)
        for category_id, link in self.store.items():
            if link.guild_id != guild.id:
                continue
            category = guild.get_channel(category_id)
            info = (
                ctflib.resolve_ctf(category)
                if isinstance(category, discord.CategoryChannel)
                else None
            )
            if info is None:
                continue
            state = (
                "🗄️ 보관됨 (동기화 중지)"
                if info.archived
                else ("⚠️ 동기화 실패 중" if category_id in self._failing else "✅ 동기화 중")
            )
            embed.add_field(
                name=info.name,
                value=(
                    f"{link.url}\n{state} · 문제 {len(link.threads)}개 · 해결 {len(link.solved)}개"
                ),
                inline=False,
            )
        if not embed.fields:
            embed.description = "연동된 CTF가 없어요. `/ctfd link` 로 연동해 보세요."
        embed.set_footer(text=f"{self.bot.settings.ctfd_poll_minutes}분마다 자동 확인")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @link_cmd.autocomplete("ctf")
    @unlink_cmd.autocomplete("ctf")
    @sync_cmd.autocomplete("ctf")
    async def ctf_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return ctflib.ctf_choices(interaction.guild, current, lambda info: not info.archived)


async def setup(bot: HayangiBot) -> None:
    """확장 진입점: CTFd 연동 코그를 봇에 등록합니다."""
    await bot.add_cog(CTFdSync(bot))
