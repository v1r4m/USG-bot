"""문제(챌린지) 관리 로직 — CTF 와 마찬가지로 Discord 상태에서 추론합니다.

    문제 카테고리 1개 = CTF 카테고리 안의 텍스트 채널 1개 (예: ``#🧩-pwn``)
    문제 1개         = 그 채널 안의 공개 스레드 1개

채널 하나에 스레드는 개수 제한이 사실상 없으므로, 문제가 수십 개인 대회도
카테고리당 채널 50개 제한에 걸리지 않습니다.

규칙
----
* 문제 카테고리 채널: 토픽이 ``"🧩 문제 카테고리: <카테고리>"`` 로 시작.
* 문제 스레드     : 문제 카테고리 채널의 공개 스레드. 이름 == 문제 이름.
* 해결한 문제     : 스레드 이름 앞에 ``✅`` 접두사.
"""

from __future__ import annotations

import discord

from hayangi import ctf as ctflib

#: 해결한 문제 스레드 이름 앞에 붙는 접두사.
SOLVED_PREFIX = "✅ "

#: 문제 카테고리 채널의 토픽 접두사. 이것으로 채널을 식별합니다.
CATEGORY_TOPIC_PREFIX = "🧩 문제 카테고리: "

#: 문제 이름 최대 길이. 스레드 이름 한도(100자)와 해결 접두사를 고려한 여유분.
CHALLENGE_NAME_MAX_LEN = 90

#: 문제 카테고리 이름 최대 길이.
CATEGORY_NAME_MAX_LEN = 50

#: 스레드가 활동이 없을 때 자동 보관되기까지의 시간(분) — 최대값인 7일.
THREAD_AUTO_ARCHIVE = 10080

#: 하양이를 상징하는 흰색 계열 임베드 색상.
EMBED_COLOR = discord.Color.from_rgb(240, 240, 240)
SOLVED_COLOR = discord.Color.green()


def ctf_of(channel: object) -> ctflib.CTFInfo | None:
    """채널(또는 스레드)이 속한 CTF. CTF 밖이면 ``None``."""
    if isinstance(channel, discord.Thread):
        channel = channel.parent
    category = getattr(channel, "category", None)
    if not isinstance(category, discord.CategoryChannel):
        return None
    return ctflib.resolve_ctf(category)


def announce_channel(info: ctflib.CTFInfo) -> discord.TextChannel | None:
    """CTF 의 공지 채널."""
    return discord.utils.get(info.category.text_channels, name=ctflib.DEFAULT_CHANNELS[0][0])


# ----------------------------------------------------------------------
# 문제 카테고리 채널
# ----------------------------------------------------------------------
def category_of_channel(channel: discord.TextChannel) -> str | None:
    """문제 카테고리 채널이면 카테고리 이름, 아니면 ``None``."""
    topic = channel.topic or ""
    if not topic.startswith(CATEGORY_TOPIC_PREFIX):
        return None
    return topic[len(CATEGORY_TOPIC_PREFIX) :].strip() or None


def category_channels(info: ctflib.CTFInfo) -> dict[str, discord.TextChannel]:
    """CTF 의 문제 카테고리 이름 → 채널."""
    found: dict[str, discord.TextChannel] = {}
    for channel in info.category.text_channels:
        name = category_of_channel(channel)
        if name is not None:
            found.setdefault(name, channel)
    return found


async def get_or_create_category_channel(
    info: ctflib.CTFInfo, category: str, *, reason: str
) -> discord.TextChannel:
    """문제 카테고리 채널을 찾고, 없으면 만듭니다 (대소문자 무시)."""
    target = category.casefold()
    for name, channel in category_channels(info).items():
        if name.casefold() == target:
            return channel
    return await info.category.create_text_channel(
        f"🧩-{category}"[:100],
        topic=f"{CATEGORY_TOPIC_PREFIX}{category}",
        reason=reason,
    )


# ----------------------------------------------------------------------
# 문제 스레드
# ----------------------------------------------------------------------
def challenge_name(thread: discord.Thread) -> str:
    """스레드 이름에서 해결 접두사를 뗀 순수 문제 이름."""
    if thread.name.startswith(SOLVED_PREFIX):
        return thread.name[len(SOLVED_PREFIX) :]
    return thread.name


def is_solved(thread: discord.Thread) -> bool:
    return thread.name.startswith(SOLVED_PREFIX)


def is_challenge_thread(thread: object) -> bool:
    """하양이 CTF 의 문제 스레드인지 여부."""
    if not isinstance(thread, discord.Thread):
        return False
    parent = thread.parent
    return (
        isinstance(parent, discord.TextChannel)
        and category_of_channel(parent) is not None
        and ctf_of(parent) is not None
    )


async def challenge_threads(channel: discord.TextChannel) -> list[discord.Thread]:
    """문제 카테고리 채널의 스레드 전부 (자동 보관된 스레드 포함)."""
    threads = list(channel.threads)
    seen = {thread.id for thread in threads}
    async for thread in channel.archived_threads(limit=None):
        if thread.id not in seen:
            threads.append(thread)
            seen.add(thread.id)
    return threads


async def find_challenge_thread(channel: discord.TextChannel, name: str) -> discord.Thread | None:
    """이름으로 문제 스레드를 찾습니다 (대소문자 무시)."""
    target = name.casefold()
    for thread in await challenge_threads(channel):
        if challenge_name(thread).casefold() == target:
            return thread
    return None


async def create_challenge_thread(
    channel: discord.TextChannel,
    name: str,
    embed: discord.Embed,
    *,
    reason: str,
) -> discord.Thread:
    """문제 스레드를 만들고 첫 메시지로 문제 정보를 남깁니다."""
    thread = await channel.create_thread(
        name=name[:100],
        type=discord.ChannelType.public_thread,
        auto_archive_duration=THREAD_AUTO_ARCHIVE,
        reason=reason,
    )
    await thread.send(embed=embed)
    return thread


async def set_solved(thread: discord.Thread, solved: bool, *, reason: str) -> bool:
    """스레드의 해결 표시를 바꿉니다. 실제로 바뀌었으면 ``True``.

    Discord 는 같은 스레드의 이름 변경을 10분에 2번으로 제한하므로, 짧은 시간에
    해결/취소를 반복하면 잠시 기다린 뒤에 반영될 수 있어요.
    """
    name = challenge_name(thread)
    new_name = f"{SOLVED_PREFIX}{name}"[:100] if solved else name
    if thread.name == new_name:
        return False
    await thread.edit(name=new_name, archived=False, reason=reason)
    return True


def challenge_embed(
    name: str,
    category: str,
    *,
    value: int | None = None,
    description: str | None = None,
    connection_info: str | None = None,
    files: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    source: str | None = None,
) -> discord.Embed:
    """문제 스레드 첫 메시지에 쓰는 문제 정보 임베드."""
    embed = discord.Embed(
        title=f"🧩 {name}",
        description=(description or "")[:4000] or None,
        color=EMBED_COLOR,
    )
    embed.add_field(name="카테고리", value=category, inline=True)
    if value is not None:
        embed.add_field(name="점수", value=str(value), inline=True)
    if tags:
        embed.add_field(name="태그", value=", ".join(tags)[:1024], inline=True)
    if connection_info:
        embed.add_field(name="접속 정보", value=f"```\n{connection_info[:1000]}\n```", inline=False)
    if files:
        lines: list[str] = []
        for url in files:
            label = url.split("?", 1)[0].rsplit("/", 1)[-1] or "파일"
            line = f"• [{label}]({url})"
            if sum(len(x) + 1 for x in lines) + len(line) > 1024:
                break
            lines.append(line)
        embed.add_field(name="첨부 파일", value="\n".join(lines), inline=False)
    embed.set_footer(text=source or "해결하면 /chal solve · 취소는 /chal unsolve")
    return embed
