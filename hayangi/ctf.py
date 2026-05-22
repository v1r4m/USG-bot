"""'Discord에서 상태를 추론'하는 CTF 관리 로직.

하양이는 별도의 데이터베이스 없이 Discord의 카테고리·역할·권한 자체를
상태 저장소로 사용합니다.

    CTF 1개 = (카테고리 1개) + (카테고리와 이름이 같은 전용 역할 1개)

규칙
----
* CTF 역할: 이름이 CTF 이름과 동일. 이 역할을 가진 멤버만 CTF 채널을 봅니다.
* CTF 카테고리: ``@everyone`` 의 ``view_channel`` 을 거부하고 CTF 역할에만 허용.
* 활성 CTF  : 카테고리 이름 == ``"<CTF 이름>"``
* 보관 CTF  : 카테고리 이름 == ``"🗄️ <CTF 이름>"``

따라서 '하양이가 관리하는 CTF 카테고리'는 다음 두 조건으로 식별합니다.

    1. 카테고리가 ``@everyone`` 의 ``view_channel`` 을 거부한다.
    2. 카테고리의 base 이름과 같은 이름의 역할이 존재한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import discord

#: 보관된 CTF 카테고리 이름 앞에 붙는 접두사.
ARCHIVE_PREFIX = "🗄️ "

#: CTF 이름 최대 길이. 역할/카테고리 이름 한도(100자)와 보관 접두사를 고려한 여유분.
CTF_NAME_MAX_LEN = 90

#: CTF 카테고리에 자동으로 만들 텍스트 채널 목록 — (채널 이름, 토픽).
DEFAULT_CHANNELS: tuple[tuple[str, str], ...] = (
    ("📢-공지", "CTF 공지 사항"),
    ("💬-일반", "자유 대화 및 협업"),
    ("📝-정보", "대회 링크 · 계정 정보 · 메모를 여기에 정리하세요"),
)


@dataclass(frozen=True, slots=True)
class CTFInfo:
    """Discord 상태로부터 추론한 CTF 1개의 정보."""

    name: str
    category: discord.CategoryChannel
    role: discord.Role
    archived: bool


def base_name(category_name: str) -> str:
    """카테고리 표시 이름에서 보관 접두사를 떼어낸 순수 CTF 이름."""
    if category_name.startswith(ARCHIVE_PREFIX):
        return category_name[len(ARCHIVE_PREFIX) :]
    return category_name


def _hidden_from_everyone(category: discord.CategoryChannel) -> bool:
    """카테고리가 ``@everyone`` 에게 숨겨져 있는지 여부."""
    overwrite = category.overwrites_for(category.guild.default_role)
    return overwrite.view_channel is False


def resolve_ctf(category: discord.CategoryChannel) -> CTFInfo | None:
    """카테고리가 하양이 CTF 이면 :class:`CTFInfo`, 아니면 ``None`` 을 반환."""
    if not _hidden_from_everyone(category):
        return None

    name = base_name(category.name)
    role = discord.utils.get(category.guild.roles, name=name)
    if role is None:
        return None

    return CTFInfo(
        name=name,
        category=category,
        role=role,
        archived=category.name.startswith(ARCHIVE_PREFIX),
    )


def list_ctfs(guild: discord.Guild) -> list[CTFInfo]:
    """길드에 존재하는 모든 하양이 CTF 목록 (이름 오름차순)."""
    found = [
        info
        for category in guild.categories
        if (info := resolve_ctf(category)) is not None
    ]
    return sorted(found, key=lambda info: info.name.casefold())


def find_ctf(guild: discord.Guild, name: str) -> CTFInfo | None:
    """이름으로 CTF 를 찾습니다 (대소문자 무시). 없으면 ``None``."""
    target = name.casefold()
    for info in list_ctfs(guild):
        if info.name.casefold() == target:
            return info
    return None
