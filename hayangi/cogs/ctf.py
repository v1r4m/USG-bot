"""CTF 대회 라이프사이클 관리 코그.

명령어: ``/ctf create · join · leave · list · archive · unarchive · delete``

``/ctf create`` 에 ``url`` · ``token`` 을 함께 주면 :mod:`hayangi.cogs.ctfd` 를 통해
CTFd 와 바로 연동합니다.

상태는 별도 DB 없이 Discord 자체에서 추론합니다. 자세한 규칙은
:mod:`hayangi.ctf` 모듈 문서를 참고하세요.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from hayangi import ctf as ctflib
from hayangi.ctfd import CTFdError

if TYPE_CHECKING:
    from hayangi.bot import HayangiBot
    from hayangi.cogs.ctfd import CTFdSync

log = logging.getLogger(__name__)

#: 하양이를 상징하는 흰색 계열 임베드 색상.
EMBED_COLOR = discord.Color.from_rgb(240, 240, 240)


async def _safe_delete(obj: discord.Role | discord.abc.GuildChannel) -> None:
    """오류 복구용 삭제 — 실패하더라도 예외를 전파하지 않습니다."""
    try:
        await obj.delete()
    except discord.DiscordException:
        log.warning("정리 중 삭제 실패: %r", obj, exc_info=True)


class ConfirmView(discord.ui.View):
    """되돌릴 수 없는 작업 전에 한 번 더 확인을 받는 버튼 뷰."""

    def __init__(self, author_id: int, *, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "이 버튼은 명령을 실행한 사람만 누를 수 있어요.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="삭제", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.value = False
        await interaction.response.defer()
        self.stop()


class CTF(commands.Cog):
    """CTF 대회의 생성·참가·보관·삭제를 담당하는 코그."""

    ctf = app_commands.Group(
        name="ctf",
        description="CTF 대회 관리",
        guild_only=True,
    )

    def __init__(self, bot: HayangiBot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # 공용 도우미
    # ------------------------------------------------------------------
    @staticmethod
    def _choices(
        interaction: discord.Interaction,
        current: str,
        predicate: Callable[[ctflib.CTFInfo], bool],
    ) -> list[app_commands.Choice[str]]:
        """자동완성용 CTF 후보 목록을 만듭니다."""
        return ctflib.ctf_choices(interaction.guild, current, predicate)

    def _validate_new_name(self, guild: discord.Guild, name: str) -> str | None:
        """새 CTF 이름을 검사해 문제가 있으면 오류 메시지를, 없으면 ``None`` 을 반환."""
        if not name:
            return "❌ CTF 이름을 입력해 주세요."
        if len(name) > ctflib.CTF_NAME_MAX_LEN:
            return f"❌ CTF 이름은 {ctflib.CTF_NAME_MAX_LEN}자 이하로 지어 주세요."
        if name.startswith(ctflib.ARCHIVE_PREFIX):
            return "❌ 그 이름은 보관 표시와 겹쳐서 쓸 수 없어요."
        if discord.utils.get(guild.roles, name=name) is not None:
            return f"❌ 이미 **{name}** 역할이 있어요. 다른 이름을 써 주세요."
        category_names = {category.name for category in guild.categories}
        if name in category_names or f"{ctflib.ARCHIVE_PREFIX}{name}" in category_names:
            return f"❌ 이미 **{name}** CTF가 있어요."
        return None

    async def _set_archived(
        self,
        info: ctflib.CTFInfo,
        archived: bool,
        actor: discord.abc.User,
    ) -> None:
        """CTF 의 보관 상태를 전환합니다 (카테고리 이름 + 채널 권한)."""
        category = info.category
        reason = f"하양이: {actor} 님이 CTF {'보관' if archived else '복구'}"

        overwrites = category.overwrites
        if archived:
            # 채널을 읽기 전용으로 — 보이긴 하되 글을 쓸 수 없게.
            overwrites[info.role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
            )
            new_name = f"{ctflib.ARCHIVE_PREFIX}{info.name}"
        else:
            overwrites[info.role] = discord.PermissionOverwrite(view_channel=True)
            new_name = info.name

        await category.edit(name=new_name, overwrites=overwrites, reason=reason)
        # 하위 채널 권한을 카테고리에 맞춰 동기화.
        for channel in category.channels:
            await channel.edit(sync_permissions=True, reason=reason)

    # ------------------------------------------------------------------
    # /ctf create
    # ------------------------------------------------------------------
    @ctf.command(
        name="create",
        description="새 CTF 대회를 만듭니다 (카테고리·채널·전용 역할 자동 생성).",
    )
    @app_commands.describe(
        name="CTF 대회 이름",
        url="(선택) CTFd 대회 주소 — 지정하면 문제를 자동으로 가져옵니다",
        token="(선택) CTFd API 토큰 또는 session 쿠키 값",
    )
    @app_commands.checks.has_permissions(manage_channels=True, manage_roles=True)
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        url: str | None = None,
        token: str | None = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None  # guild_only 그룹

        name = " ".join(name.split())  # 앞뒤·중복 공백 정리
        error = self._validate_new_name(guild, name)
        if error is None and bool(url) != bool(token):
            error = "❌ CTFd 연동에는 `url` 과 `token` 이 둘 다 필요해요."
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        role: discord.Role | None = None
        category: discord.CategoryChannel | None = None
        reason = f"하양이: {interaction.user} 님이 CTF 생성"
        try:
            role = await guild.create_role(
                name=name,
                mentionable=True,
                colour=discord.Colour.random(),
                reason=reason,
            )
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                role: discord.PermissionOverwrite(view_channel=True),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    create_public_threads=True,
                    send_messages_in_threads=True,
                    manage_threads=True,
                ),
            }
            category = await guild.create_category(
                name, overwrites=overwrites, reason=reason
            )
            channels: list[discord.TextChannel] = []
            for channel_name, topic in ctflib.DEFAULT_CHANNELS:
                channels.append(
                    await category.create_text_channel(
                        channel_name, topic=topic, reason=reason
                    )
                )
            await interaction.user.add_roles(role, reason=reason)
        except discord.DiscordException:
            # 일부만 만들어진 채로 실패하면 흔적을 지운 뒤 오류 핸들러로 넘깁니다.
            if category is not None:
                for channel in list(category.channels):
                    await _safe_delete(channel)
                await _safe_delete(category)
            if role is not None:
                await _safe_delete(role)
            raise

        log.info("CTF 생성: '%s' (요청자: %s)", name, interaction.user)

        # 공지 채널에 환영 메시지.
        await channels[0].send(
            embed=discord.Embed(
                title=f"🤍 {name}",
                description=(
                    "새 CTF 채널이 열렸어요!\n"
                    f"참가하려면 `/ctf join` 에서 **{name}** 을 선택하세요."
                ),
                color=EMBED_COLOR,
            )
        )

        result = discord.Embed(title="✅ CTF 생성 완료", color=EMBED_COLOR)
        result.add_field(name="이름", value=name, inline=False)
        result.add_field(name="역할", value=role.mention, inline=True)
        result.add_field(
            name="채널",
            value=" ".join(channel.mention for channel in channels),
            inline=False,
        )
        result.set_footer(text="참가: /ctf join · 문제 추가: /chal add · 보관: /ctf archive")

        if url and token:
            result.add_field(name="CTFd", value=await self._link_ctfd(category, url, token))

        await interaction.followup.send(embed=result)

    async def _link_ctfd(self, category: discord.CategoryChannel, url: str, token: str) -> str:
        """새 CTF 를 CTFd 와 연동하고 결과 요약 문구를 돌려줍니다."""
        # 확장은 load_extension 이 모듈을 따로 불러오므로 클래스 대신 코그 이름으로 찾습니다.
        cog: CTFdSync | None = self.bot.get_cog("CTFd")  # type: ignore[assignment]
        info = ctflib.resolve_ctf(category)
        if cog is None or info is None:
            return "⚠️ CTFd 연동 기능을 불러오지 못했어요. `/ctfd link` 로 다시 시도해 주세요."
        try:
            synced = await cog.link(info, url, token)
        except CTFdError as exc:
            return f"⚠️ 연동 실패: {exc}\n`/ctfd link` 로 다시 시도할 수 있어요."
        return f"🔗 연동 완료 — 문제 {len(synced.created)}개를 가져왔어요."

    # ------------------------------------------------------------------
    # /ctf join
    # ------------------------------------------------------------------
    @ctf.command(name="join", description="진행 중인 CTF에 참가합니다.")
    @app_commands.describe(name="참가할 CTF 이름")
    async def join(self, interaction: discord.Interaction, name: str) -> None:
        guild = interaction.guild
        assert guild is not None

        info = ctflib.find_ctf(guild, name)
        if info is None:
            await interaction.response.send_message(
                f"❌ **{name}** CTF를 찾을 수 없어요.", ephemeral=True
            )
            return
        if info.archived:
            await interaction.response.send_message(
                f"🗄️ **{info.name}** 은 보관된 CTF라 참가할 수 없어요.", ephemeral=True
            )
            return

        member = interaction.user
        if info.role in member.roles:
            await interaction.response.send_message(
                f"이미 **{info.name}** 에 참가 중이에요.", ephemeral=True
            )
            return

        await member.add_roles(info.role, reason=f"하양이: {member} 님이 CTF 참가")
        log.info("CTF 참가: '%s' <- %s", info.name, member)
        await interaction.response.send_message(
            f"✅ **{info.name}** 에 참가했어요! 이제 해당 카테고리의 채널이 보일 거예요.",
            ephemeral=True,
        )

    @join.autocomplete("name")
    async def join_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        roles = getattr(interaction.user, "roles", [])
        return self._choices(
            interaction,
            current,
            lambda info: not info.archived and info.role not in roles,
        )

    # ------------------------------------------------------------------
    # /ctf leave
    # ------------------------------------------------------------------
    @ctf.command(name="leave", description="참가 중인 CTF에서 나갑니다.")
    @app_commands.describe(name="나갈 CTF 이름")
    async def leave(self, interaction: discord.Interaction, name: str) -> None:
        guild = interaction.guild
        assert guild is not None

        info = ctflib.find_ctf(guild, name)
        if info is None:
            await interaction.response.send_message(
                f"❌ **{name}** CTF를 찾을 수 없어요.", ephemeral=True
            )
            return

        member = interaction.user
        if info.role not in member.roles:
            await interaction.response.send_message(
                f"**{info.name}** 에 참가 중이 아니에요.", ephemeral=True
            )
            return

        await member.remove_roles(info.role, reason=f"하양이: {member} 님이 CTF 탈퇴")
        log.info("CTF 탈퇴: '%s' <- %s", info.name, member)
        await interaction.response.send_message(
            f"👋 **{info.name}** 에서 나왔어요.", ephemeral=True
        )

    @leave.autocomplete("name")
    async def leave_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        roles = getattr(interaction.user, "roles", [])
        return self._choices(interaction, current, lambda info: info.role in roles)

    # ------------------------------------------------------------------
    # /ctf list
    # ------------------------------------------------------------------
    @ctf.command(name="list", description="이 서버의 CTF 목록을 보여줍니다.")
    async def list_ctfs_cmd(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None

        ctfs = ctflib.list_ctfs(guild)
        embed = discord.Embed(title="🤍 CTF 목록", color=EMBED_COLOR)

        if not ctfs:
            embed.description = (
                "아직 만들어진 CTF가 없어요. `/ctf create` 로 시작해 보세요!"
            )
        else:
            active = [info for info in ctfs if not info.archived]
            archived = [info for info in ctfs if info.archived]
            if active:
                embed.add_field(
                    name=f"진행 중 ({len(active)})",
                    value="\n".join(f"• **{info.name}**" for info in active),
                    inline=False,
                )
            if archived:
                embed.add_field(
                    name=f"보관됨 ({len(archived)})",
                    value="\n".join(f"• {info.name}" for info in archived),
                    inline=False,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /ctf archive
    # ------------------------------------------------------------------
    @ctf.command(
        name="archive",
        description="CTF를 보관합니다 (채널을 읽기 전용으로 전환).",
    )
    @app_commands.describe(name="보관할 CTF 이름")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def archive(self, interaction: discord.Interaction, name: str) -> None:
        guild = interaction.guild
        assert guild is not None

        info = ctflib.find_ctf(guild, name)
        if info is None:
            await interaction.response.send_message(
                f"❌ **{name}** CTF를 찾을 수 없어요.", ephemeral=True
            )
            return
        if info.archived:
            await interaction.response.send_message(
                f"**{info.name}** 은 이미 보관된 상태예요.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        await self._set_archived(info, True, interaction.user)
        log.info("CTF 보관: '%s' (요청자: %s)", info.name, interaction.user)
        await interaction.followup.send(
            embed=discord.Embed(
                title="🗄️ CTF 보관 완료",
                description=(
                    f"**{info.name}** 을 보관했어요. "
                    "채널은 읽기 전용으로 남으며, `/ctf unarchive` 로 되돌릴 수 있어요."
                ),
                color=EMBED_COLOR,
            )
        )

    @archive.autocomplete("name")
    async def archive_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return self._choices(interaction, current, lambda info: not info.archived)

    # ------------------------------------------------------------------
    # /ctf unarchive
    # ------------------------------------------------------------------
    @ctf.command(
        name="unarchive",
        description="보관한 CTF를 다시 활성 상태로 되돌립니다.",
    )
    @app_commands.describe(name="복구할 CTF 이름")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unarchive(self, interaction: discord.Interaction, name: str) -> None:
        guild = interaction.guild
        assert guild is not None

        info = ctflib.find_ctf(guild, name)
        if info is None:
            await interaction.response.send_message(
                f"❌ **{name}** CTF를 찾을 수 없어요.", ephemeral=True
            )
            return
        if not info.archived:
            await interaction.response.send_message(
                f"**{info.name}** 은 이미 활성 상태예요.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        await self._set_archived(info, False, interaction.user)
        log.info("CTF 복구: '%s' (요청자: %s)", info.name, interaction.user)
        await interaction.followup.send(
            embed=discord.Embed(
                title="📂 CTF 복구 완료",
                description=f"**{info.name}** 을 다시 활성 상태로 되돌렸어요.",
                color=EMBED_COLOR,
            )
        )

    @unarchive.autocomplete("name")
    async def unarchive_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return self._choices(interaction, current, lambda info: info.archived)

    # ------------------------------------------------------------------
    # /ctf delete
    # ------------------------------------------------------------------
    @ctf.command(
        name="delete",
        description="CTF를 완전히 삭제합니다 (카테고리·채널·역할 제거, 되돌릴 수 없음).",
    )
    @app_commands.describe(name="삭제할 CTF 이름")
    @app_commands.checks.has_permissions(manage_channels=True, manage_roles=True)
    async def delete(self, interaction: discord.Interaction, name: str) -> None:
        guild = interaction.guild
        assert guild is not None

        info = ctflib.find_ctf(guild, name)
        if info is None:
            await interaction.response.send_message(
                f"❌ **{name}** CTF를 찾을 수 없어요.", ephemeral=True
            )
            return

        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ **{info.name}** CTF의 카테고리·채널·역할을 모두 삭제합니다.\n"
            "채팅 기록도 함께 사라지며 **되돌릴 수 없어요.** 정말 삭제할까요?",
            view=view,
            ephemeral=True,
        )
        await view.wait()

        if view.value is None:
            await interaction.edit_original_response(
                content="⏱️ 시간이 초과되어 삭제를 취소했어요.", view=None
            )
            return
        if not view.value:
            await interaction.edit_original_response(
                content="삭제를 취소했어요.", view=None
            )
            return

        await interaction.edit_original_response(
            content=f"🗑️ **{info.name}** 삭제 중...", view=None
        )
        reason = f"하양이: {interaction.user} 님이 CTF 삭제"
        for channel in list(info.category.channels):
            await channel.delete(reason=reason)
        await info.category.delete(reason=reason)
        await info.role.delete(reason=reason)
        self.bot.store.remove(info.category.id)
        log.info("CTF 삭제: '%s' (요청자: %s)", info.name, interaction.user)

        try:
            await interaction.edit_original_response(
                content=f"🗑️ **{info.name}** CTF를 삭제했어요."
            )
        except discord.HTTPException:
            # 명령을 그 CTF 안의 채널에서 실행했다면 원본 메시지가 이미 사라졌을 수 있음.
            pass

    @delete.autocomplete("name")
    async def delete_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return self._choices(interaction, current, lambda info: True)


async def setup(bot: HayangiBot) -> None:
    """확장 진입점: CTF 코그를 봇에 등록합니다."""
    await bot.add_cog(CTF(bot))
