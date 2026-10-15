"""CTFd REST API 클라이언트 (읽기 전용).

하양이는 CTFd 의 문제 목록과 우리 팀의 풀이 여부만 읽어 옵니다.
인증 정보는 두 가지를 받습니다.

* **API 토큰** — CTFd 설정 → Access Tokens 에서 발급 (``ctfd_`` 로 시작)
* **세션 쿠키** — 브라우저 개발자 도구에서 복사한 ``session`` 쿠키 값
  (토큰 발급을 막아 둔 대회용)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

#: CTFd 요청 1건의 최대 대기 시간.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)

#: CTFd API 토큰의 접두사. 이것으로 시작하지 않으면 세션 쿠키로 취급합니다.
TOKEN_PREFIX = "ctfd_"

NOT_CTFD_HINT = "CTFd로 운영하는 대회 주소가 맞는지 확인해 주세요."


class CTFdError(Exception):
    """CTFd 요청 실패. 메시지는 사용자에게 그대로 보여줄 수 있는 문장입니다."""


@dataclass(frozen=True, slots=True)
class Challenge:
    """문제 목록(``/api/v1/challenges``)의 항목 1개."""

    id: int
    name: str
    category: str
    value: int
    solved: bool


@dataclass(frozen=True, slots=True)
class ChallengeDetail:
    """문제 상세(``/api/v1/challenges/<id>``)."""

    id: int
    name: str
    category: str
    value: int
    description: str
    connection_info: str | None
    files: tuple[str, ...]
    tags: tuple[str, ...]


def normalize_url(url: str) -> str:
    """사용자가 입력한 대회 주소를 ``https://host[/path]`` 형태로 정리합니다.

    Raises:
        CTFdError: 주소 형식이 올바르지 않은 경우.
    """
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise CTFdError(f"올바른 대회 주소가 아니에요: `{url}`")
    return f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")


def _category(raw: Any) -> str:
    text = " ".join(str(raw or "").split())
    return text or "misc"


class CTFdClient:
    """CTFd 대회 1개에 대한 API 클라이언트."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, credential: str) -> None:
        self.session = session
        self.base_url = base_url
        self.credential = credential

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.credential.startswith(TOKEN_PREFIX):
            headers["Authorization"] = f"Token {self.credential}"
        else:
            headers["Cookie"] = f"session={self.credential}"
        return headers

    async def _get(self, path: str) -> Any:
        """``GET <base>/api/v1/<path>`` 의 ``data`` 필드를 돌려줍니다."""
        url = f"{self.base_url}/api/v1/{path}"
        try:
            async with self.session.get(
                url,
                headers=self._headers(),
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                # 인증이 안 되면 CTFd 는 로그인 페이지로 리다이렉트하거나 401 을 줍니다.
                if 300 <= resp.status < 400 or resp.status == 401:
                    raise CTFdError("CTFd 인증에 실패했어요. 토큰이나 세션 값을 확인해 주세요.")
                if resp.status == 403:
                    message = await self._error_message(resp)
                    raise CTFdError(
                        "CTFd가 접근을 거부했어요 (403)"
                        + (f": {message}" if message else "")
                        + ". 대회가 아직 시작하지 않았거나 권한이 없을 수 있어요."
                    )
                if resp.status == 404:
                    raise CTFdError("CTFd API를 찾지 못했어요. " + NOT_CTFD_HINT)
                if resp.status >= 400:
                    raise CTFdError(f"CTFd가 오류를 돌려줬어요 (HTTP {resp.status}).")
                try:
                    payload = await resp.json(content_type=None)
                except ValueError as exc:
                    raise CTFdError("CTFd 응답을 해석하지 못했어요. " + NOT_CTFD_HINT) from exc
        except aiohttp.ClientError as exc:
            raise CTFdError(f"CTFd에 연결하지 못했어요: {exc}") from exc
        except TimeoutError as exc:
            raise CTFdError("CTFd 응답 시간이 초과됐어요.") from exc

        if not isinstance(payload, dict) or not payload.get("success"):
            raise CTFdError("CTFd가 요청을 처리하지 못했어요.")
        return payload.get("data")

    @staticmethod
    async def _error_message(resp: aiohttp.ClientResponse) -> str | None:
        try:
            payload = await resp.json(content_type=None)
        except ValueError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            return payload["message"]
        return None

    async def challenges(self) -> list[Challenge]:
        """현재 열려 있는 문제 목록. 선행 조건 때문에 숨겨진 문제는 제외합니다."""
        data = await self._get("challenges")
        if not isinstance(data, list):
            raise CTFdError("CTFd 문제 목록 형식이 예상과 달라요.")

        result: list[Challenge] = []
        for item in data:
            if not isinstance(item, dict) or item.get("type") == "hidden":
                continue
            name = " ".join(str(item.get("name") or "").split())
            if not isinstance(item.get("id"), int) or not name:
                continue
            result.append(
                Challenge(
                    id=item["id"],
                    name=name,
                    category=_category(item.get("category")),
                    value=int(item.get("value") or 0),
                    solved=bool(item.get("solved_by_me")),
                )
            )
        return result

    async def challenge(self, challenge_id: int) -> ChallengeDetail:
        """문제 1개의 설명·접속 정보·첨부 파일."""
        data = await self._get(f"challenges/{challenge_id}")
        if not isinstance(data, dict):
            raise CTFdError("CTFd 문제 상세 형식이 예상과 달라요.")

        files = tuple(
            urljoin(f"{self.base_url}/", path)
            for path in data.get("files") or ()
            if isinstance(path, str)
        )
        tags = tuple(
            str(tag.get("value") if isinstance(tag, dict) else tag)
            for tag in data.get("tags") or ()
        )
        connection = data.get("connection_info")
        return ChallengeDetail(
            id=challenge_id,
            name=" ".join(str(data.get("name") or "").split()),
            category=_category(data.get("category")),
            value=int(data.get("value") or 0),
            description=str(data.get("description") or "").strip(),
            connection_info=str(connection).strip() if connection else None,
            files=files,
            tags=tags,
        )
