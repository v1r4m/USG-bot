"""CTFd 연동 정보 저장소.

CTF 자체의 상태는 여전히 Discord 에서 추론하지만, CTFd 인증 정보만큼은
채널에 남기면 안 되므로 봇 서버의 JSON 파일 하나에 따로 보관합니다.

    {
      "<카테고리 ID>": {
        "guild_id": 123,
        "url": "https://ctf.example.com",
        "credential": "ctfd_...",
        "threads": {"<CTFd 문제 ID>": <스레드 ID>},
        "solved": [<CTFd 문제 ID>, ...]
      }
    }

``threads`` 는 이미 스레드를 만든 문제, ``solved`` 는 이미 해결 처리한 문제를
기억해 같은 작업을 반복하지 않게 합니다.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CTFdLink:
    """CTF 1개와 CTFd 대회 1개의 연결."""

    guild_id: int
    url: str
    credential: str
    threads: dict[int, int] = field(default_factory=dict)
    solved: set[int] = field(default_factory=set)

    def to_json(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "url": self.url,
            "credential": self.credential,
            "threads": {str(k): v for k, v in self.threads.items()},
            "solved": sorted(self.solved),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CTFdLink:
        return cls(
            guild_id=int(data["guild_id"]),
            url=str(data["url"]),
            credential=str(data["credential"]),
            threads={int(k): int(v) for k, v in data.get("threads", {}).items()},
            solved={int(v) for v in data.get("solved", [])},
        )


class LinkStore:
    """카테고리 ID → :class:`CTFdLink` 를 JSON 파일로 보관합니다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._links: dict[int, CTFdLink] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._links = {int(k): CTFdLink.from_json(v) for k, v in raw.items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # 깨진 파일 때문에 봇이 재시작을 반복하지 않도록 옆으로 치워 둡니다.
            broken = self.path.with_suffix(".broken.json")
            log.exception("연동 정보 파일을 읽지 못했어요 — %s 로 옮기고 새로 시작합니다.", broken)
            self.path.replace(broken)
            self._links = {}
        else:
            log.info("CTFd 연동 %d개를 불러왔어요.", len(self._links))

    def save(self) -> None:
        """임시 파일에 쓴 뒤 바꿔치기해서 저장 중 종료돼도 파일이 깨지지 않게 합니다."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {str(k): v.to_json() for k, v in self._links.items()}
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self, category_id: int) -> CTFdLink | None:
        return self._links.get(category_id)

    def items(self) -> list[tuple[int, CTFdLink]]:
        return list(self._links.items())

    def set(self, category_id: int, link: CTFdLink) -> None:
        self._links[category_id] = link
        self.save()

    def remove(self, category_id: int) -> bool:
        if self._links.pop(category_id, None) is None:
            return False
        self.save()
        return True
